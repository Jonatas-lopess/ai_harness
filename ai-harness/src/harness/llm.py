"""Contrato com o provedor de LLM: tipos, erros e leitura da resposta. Sem SDK e sem nada de domínio.

Quem fala com um SDK real (Groq, ...) implementa `LLMClient` fora daqui e devolve `Completion`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class Completion:
    """Resposta do provedor no formato do harness, sem depender do SDK."""

    content: str | None
    finish_reason: str
    refusal: str | None = None
    usage: Usage | None = None


class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any],  # pyright: ignore[reportExplicitAny]
        max_completion_tokens: int,
    ) -> Completion: ...


class ExtractionError(Exception):
    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage: Usage | None = usage


class TruncatedOutputError(ExtractionError):
    pass


class RefusedError(ExtractionError):
    pass


class InvalidOutputError(ExtractionError):
    pass


class ProviderUnavailableError(ExtractionError):
    """Provedor indisponível (rate limit, timeout, 5xx) depois dos retries do adaptador."""


def add_usage(total: Usage, extra: Usage | None) -> Usage:
    if extra is None:
        return total
    return Usage(
        total.prompt_tokens + extra.prompt_tokens,
        total.completion_tokens + extra.completion_tokens,
    )


def with_feedback(text: str, error: InvalidOutputError) -> str:
    """Texto da retentativa: o pedido original mais o motivo da rejeição.

    Dívida: a frase está fixa em português; um pack em outro idioma recebe a correção em português.
    """
    return (
        f"{text}\n\n"
        f"Sua resposta anterior foi rejeitada: {error}\n"
        "Corrija e responda de novo seguindo o schema."
    )


def parse_completion[T: BaseModel](completion: Completion, model: type[T]) -> T:
    if completion.finish_reason == "length":
        raise TruncatedOutputError("output cut at max_completion_tokens", completion.usage)
    if completion.refusal is not None:
        raise RefusedError(f"model refused: {completion.refusal}", completion.usage)
    if not completion.content:
        raise InvalidOutputError("empty output", completion.usage)

    try:
        return model.model_validate_json(completion.content)
    except ValidationError as exc:
        raise InvalidOutputError(f"output does not match schema: {exc}", completion.usage) from exc
