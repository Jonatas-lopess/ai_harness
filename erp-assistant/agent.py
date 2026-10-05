"""Loop do agente: o modelo pede tools, o nosso código executa e devolve o resultado."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from pydantic import BaseModel

from extract import (
    ExtractionError,
    InvalidOutputError,
    TruncatedOutputError,
    Usage,
    add_usage,
)
from tools import ToolContext, ToolError, ToolRegistry, ToolSchema

DEFAULT_MAX_COMPLETION_TOKENS = 1024


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # texto JSON como o modelo gerou; pode estar quebrado


@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolMessage:
    tool_call_id: str
    content: str


type Message = UserMessage | AssistantMessage | ToolMessage


@dataclass(frozen=True)
class ChatResponse:
    """Resposta do provedor no formato do harness, sem depender do SDK."""

    message: AssistantMessage
    finish_reason: str
    usage: Usage | None = None


class ChatClient(Protocol):
    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_completion_tokens: int,
    ) -> ChatResponse: ...


@dataclass(frozen=True)
class ToolCallRecord:
    """Uma tool executada: serve ao validador do passo 5 (todo número do texto veio de uma tool?)."""

    name: str
    arguments: str
    result: BaseModel


@dataclass(frozen=True)
class AgentResult:
    text: str
    usage: Usage  # soma de todas as chamadas ao modelo
    steps: int  # chamadas ao modelo
    tool_calls: tuple[ToolCallRecord, ...]


class BudgetExceededError(Exception):
    """O loop não convergiu em `max_steps`. Carrega o custo e as tools já chamadas: nada se perde."""

    def __init__(self, message: str, usage: Usage, tool_calls: tuple[ToolCallRecord, ...]) -> None:
        super().__init__(message)
        self.usage: Usage = usage
        self.tool_calls: tuple[ToolCallRecord, ...] = tool_calls


def _parse_arguments(raw: str) -> dict[str, object] | ToolError:
    """Argumentos do modelo são input não confiável: JSON quebrado ou não-objeto volta como erro."""
    if not raw.strip():
        return {}  # tool sem parâmetros: alguns modelos mandam texto vazio em vez de `{}`
    try:
        parsed: object = json.loads(raw)  # pyright: ignore[reportAny]
    except json.JSONDecodeError as exc:
        return ToolError(error=f"arguments are not valid JSON: {exc.msg}")
    if not isinstance(parsed, dict):
        return ToolError(error="arguments must be a JSON object")
    return cast("dict[str, object]", parsed)


def run_agent(
    client: ChatClient,
    registry: ToolRegistry,
    ctx: ToolContext,
    *,
    model: str,
    system: str,
    user: str,
    max_steps: int,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
) -> AgentResult:
    """Chama o modelo até ele responder sem pedir tool, no máximo `max_steps` vezes.

    A API não guarda estado: cada chamada reenvia o histórico inteiro, então o custo cresce a cada volta.
    """
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")

    total = Usage(0, 0)
    records: list[ToolCallRecord] = []
    messages: list[Message] = [UserMessage(user)]
    tools = registry.schemas()

    for step in range(1, max_steps + 1):
        try:
            response = client.chat(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_completion_tokens=max_completion_tokens,
            )
        except ExtractionError as exc:
            exc.usage = total  # erro do provedor não traz uso; sobe com o acumulado
            raise
        total = add_usage(total, response.usage)

        message = response.message
        messages.append(message)

        if not message.tool_calls:
            if response.finish_reason == "length":
                raise TruncatedOutputError("final answer cut at max_completion_tokens", total)
            if not message.content:
                raise InvalidOutputError("empty final answer", total)
            return AgentResult(message.content, total, step, tuple(records))

        # Toda tool_call precisa de uma resposta, inclusive quando vêm várias na mesma volta.
        for call in message.tool_calls:
            parsed = _parse_arguments(call.arguments)
            result = parsed if isinstance(parsed, ToolError) else registry.call(call.name, ctx, parsed)
            records.append(ToolCallRecord(call.name, call.arguments, result))
            messages.append(ToolMessage(call.id, result.model_dump_json()))

    raise BudgetExceededError(f"no final answer after {max_steps} steps", total, tuple(records))
