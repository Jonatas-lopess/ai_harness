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


def extract_text(
    client: LLMClient,
    text: str,
    *,
    model: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
) -> StockMessage:
    completion = client.complete(
        model=model,
        system=SYSTEM_PROMPT,
        user=text,
        response_schema=StockMessage.model_json_schema(),
        max_completion_tokens=max_completion_tokens,
    )

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
