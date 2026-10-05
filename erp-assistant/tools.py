"""Mecanismo de tools: genérico, sem nada de ERP (candidato a ir para o harness na fase 5)."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

import psycopg
from pydantic import BaseModel, ConfigDict, ValidationError


@dataclass(frozen=True)
class ToolContext:
    """O que o harness injeta em toda tool. O modelo nunca escolhe estes valores (ex.: `as_of`)."""

    conn: psycopg.Connection
    as_of: date


class ToolInput(BaseModel):
    """Base dos argumentos de tool. `extra="forbid"`: argumento inventado pelo modelo é rejeitado."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ToolError(BaseModel):
    """Erro esperado (argumento inválido, entidade inexistente): volta ao modelo como resultado."""

    error: str


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, object]
    run_fn: Callable[[ToolContext, Mapping[str, object]], BaseModel]

    def run(self, ctx: ToolContext, raw_args: Mapping[str, object]) -> BaseModel:
        return self.run_fn(ctx, raw_args)


def make_tool[InputT: BaseModel](
    name: str,
    description: str,
    input_model: type[InputT],
    fn: Callable[[ToolContext, InputT], BaseModel],
) -> Tool:
    def run(ctx: ToolContext, raw_args: Mapping[str, object]) -> BaseModel:
        try:
            args = input_model.model_validate(raw_args)
        except ValidationError as exc:
            return ToolError(error=_format_validation_error(exc))
        return fn(ctx, args)

    return Tool(
        name=name,
        description=description,
        parameters=input_model.model_json_schema(),
        run_fn=run,
    )


def _format_validation_error(exc: ValidationError) -> str:
    problems = [f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors()]
    return "invalid arguments: " + "; ".join(problems)


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, object]]:
        """Nome + descrição + JSON Schema: tudo o que o modelo vê de cada tool."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    def call(self, name: str, ctx: ToolContext, raw_args: Mapping[str, object]) -> BaseModel:
        tool = self._tools.get(name)
        if tool is None:
            return ToolError(error=f"unknown tool '{name}'; available: {', '.join(self._tools)}")
        return tool.run(ctx, raw_args)


def connect_readonly(url: str) -> psycopg.Connection:
    """Conexão em que o Postgres recusa qualquer escrita, mesmo que uma tool tente.

    Defesa em profundidade; em produção o ideal é também uma role sem INSERT/UPDATE/DELETE.
    """
    return psycopg.connect(url, options="-c default_transaction_read_only=on")
