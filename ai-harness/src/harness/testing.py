"""Dublês de LLM para testes e evals de qualquer pack: respostas prontas, sem rede, sem custo.

Ficam no pacote (não em `tests/`) para o ERP e o Legal os importarem em vez de cada um copiar o seu."""

import json
from collections.abc import Sequence
from typing import Any

from harness.agent import AssistantMessage, ChatResponse, Message, ToolCall
from harness.llm import Completion, Usage
from harness.tools import ToolSchema


class FixedClient:
    """Responde sempre o mesmo texto, em todas as tentativas."""

    def __init__(self, text: str) -> None:
        self.text: str = text

    def complete(self, **_: Any) -> Completion:  # pyright: ignore[reportExplicitAny]
        return Completion(json.dumps({"rationale": self.text}), "stop", usage=Usage(0, 0))


class ScriptedChat:
    """Agente simulado: devolve uma resposta por volta, na ordem. Sem tool calls = resposta final."""

    def __init__(self, *responses: ChatResponse) -> None:
        self._responses: list[ChatResponse] = list(responses)

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_completion_tokens: int,
    ) -> ChatResponse:
        del model, system, messages, tools, max_completion_tokens
        return self._responses.pop(0)


def final(text: str) -> ChatResponse:
    return ChatResponse(AssistantMessage(text), "stop", Usage(0, 0))


def call_tool(name: str, arguments: str = "{}") -> ChatResponse:
    return ChatResponse(
        AssistantMessage(None, (ToolCall("c1", name, arguments),)), "tool_calls", Usage(0, 0)
    )
