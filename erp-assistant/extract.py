from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

SYSTEM_PROMPT = (
    "Extraia produto e nível de estoque da mensagem do usuário. "
    "Se a mensagem não informar um campo, use null. Nunca infira nem invente valores."
)
DEFAULT_MAX_COMPLETION_TOKENS = 256


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


class StockMessage(BaseModel):
    # extra="forbid" gera `additionalProperties: false` no JSON Schema (exigido pelo modo strict).
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    # Sem default de propósito: o schema marca o campo como obrigatório, e o modelo deve
    # responder `null` explicitamente quando a mensagem não traz o dado.
    product_name: str | None
    stock_level: int | None


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


@dataclass(frozen=True)
class ExtractionResult:
    value: StockMessage
    usage: Usage  # soma de todas as tentativas, inclusive as que falharam
    attempts: int


def _add_usage(total: Usage, extra: Usage | None) -> Usage:
    if extra is None:
        return total
    return Usage(
        total.prompt_tokens + extra.prompt_tokens,
        total.completion_tokens + extra.completion_tokens,
    )


def _call(
    client: LLMClient, user: str, model: str, max_completion_tokens: int
) -> Completion:
    return client.complete(
        model=model,
        system=SYSTEM_PROMPT,
        user=user,
        response_schema=StockMessage.model_json_schema(),
        max_completion_tokens=max_completion_tokens,
    )


def _with_feedback(text: str, error: InvalidOutputError) -> str:
    return (
        f"{text}\n\n"
        f"Sua resposta anterior foi rejeitada: {error}\n"
        "Corrija e responda de novo seguindo o schema."
    )


def extract_text(
    client: LLMClient,
    text: str,
    *,
    model: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
) -> StockMessage:
    return _parse(_call(client, text, model, max_completion_tokens))


def extract_with_retry(
    client: LLMClient,
    text: str,
    *,
    model: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    max_attempts: int = 3,
) -> ExtractionResult:
    """Reenvia só em `InvalidOutputError`, anexando o erro ao prompt; soma o uso de todas as tentativas."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    total = Usage(0, 0)
    user = text
    last_error: InvalidOutputError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            completion = _call(client, user, model, max_completion_tokens)
            total = _add_usage(total, completion.usage)
            value = _parse(completion)
        except InvalidOutputError as exc:
            last_error = exc
            user = _with_feedback(text, exc)
            continue
        except ExtractionError as exc:
            # Sem retry: o erro sobe, mas com o uso acumulado (já inclui esta tentativa).
            exc.usage = total
            raise
        return ExtractionResult(value, total, attempt)

    raise InvalidOutputError(
        f"invalid output after {max_attempts} attempts: {last_error}", total
    ) from last_error


def _parse(completion: Completion) -> StockMessage:
    if completion.finish_reason == "length":
        raise TruncatedOutputError("output cut at max_completion_tokens", completion.usage)
    if completion.refusal is not None:
        raise RefusedError(f"model refused: {completion.refusal}", completion.usage)
    if not completion.content:
        raise InvalidOutputError("empty output", completion.usage)

    try:
        return StockMessage.model_validate_json(completion.content)
    except ValidationError as exc:
        raise InvalidOutputError(f"output does not match schema: {exc}", completion.usage) from exc
