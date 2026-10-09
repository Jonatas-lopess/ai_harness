"""Mecanismo de tools: genérico, sem nada de ERP.

O contexto (`C`) é um parâmetro de tipo: o harness só o repassa à tool. Cada pack define o seu
(conexão de banco, cliente HTTP, data de referência...), então nada de domínio entra aqui.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolInput(BaseModel):
    """Base dos argumentos de tool. `extra="forbid"`: argumento inventado pelo modelo é rejeitado."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ToolSchema(TypedDict):
    """O que o modelo vê de cada tool."""

    name: str
    description: str
    parameters: dict[str, object]


class ToolError(BaseModel):
    """Erro esperado (argumento inválido, entidade inexistente): volta ao modelo como resultado."""

    error: str


@dataclass(frozen=True)
class Tool[C]:
    name: str
    description: str
    parameters: dict[str, object]
    run_fn: Callable[[C, Mapping[str, object]], BaseModel]

    def run(self, ctx: C, raw_args: Mapping[str, object]) -> BaseModel:
        return self.run_fn(ctx, raw_args)


def make_tool[C, InputT: BaseModel](
    name: str,
    description: str,
    input_model: type[InputT],
    fn: Callable[[C, InputT], BaseModel],
) -> Tool[C]:
    def run(ctx: C, raw_args: Mapping[str, object]) -> BaseModel:
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


class ToolRegistry[C]:
    def __init__(self, tools: Sequence[Tool[C]]) -> None:
        self._tools: dict[str, Tool[C]] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(name=t.name, description=t.description, parameters=t.parameters)
            for t in self._tools.values()
        ]

    def call(self, name: str, ctx: C, raw_args: Mapping[str, object]) -> BaseModel:
        tool = self._tools.get(name)
        if tool is None:
            return ToolError(error=f"unknown tool '{name}'; available: {', '.join(self._tools)}")
        return tool.run(ctx, raw_args)

