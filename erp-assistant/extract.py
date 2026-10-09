"""Exercício da fase 1: extrair `StockMessage` de um texto. Fica no pack; o harness só tem o contrato (`harness.llm`).

Nenhum job de produção usa estas funções (eles usam `narrate`); o retry daqui é o do exercício.
"""

import asyncio
import logging
from decimal import Decimal
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from harness.llm import (
    Completion,
    ExtractionError,
    InvalidOutputError,
    LLMClient,
    Usage,
    add_usage,
    parse_completion,
    with_feedback,
)
from harness.pricing import PriceTable, compute_cost

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Extraia produto e nível de estoque da mensagem do usuário. "
    "Se a mensagem não informar um campo, use null. Nunca infira nem invente valores."
)
DEFAULT_MAX_COMPLETION_TOKENS = 256


class AsyncLLMClient(Protocol):
    async def complete(
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


@dataclass(frozen=True)
class ExtractionResult:
    value: StockMessage
    usage: Usage  # soma de todas as tentativas, inclusive as que falharam
    attempts: int


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


async def _acall(
    client: AsyncLLMClient, user: str, model: str, max_completion_tokens: int
) -> Completion:
    return await client.complete(
        model=model,
        system=SYSTEM_PROMPT,
        user=user,
        response_schema=StockMessage.model_json_schema(),
        max_completion_tokens=max_completion_tokens,
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
            total = add_usage(total, completion.usage)
            value = _parse(completion)
        except InvalidOutputError as exc:
            last_error = exc
            user = with_feedback(text, exc)
            continue
        except ExtractionError as exc:
            # Sem retry: o erro sobe, mas com o uso acumulado (já inclui esta tentativa).
            exc.usage = total
            raise
        return ExtractionResult(value, total, attempt)

    raise InvalidOutputError(
        f"invalid output after {max_attempts} attempts: {last_error}", total
    ) from last_error


async def aextract_with_retry(
    client: AsyncLLMClient,
    text: str,
    *,
    model: str,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    max_attempts: int = 3,
) -> ExtractionResult:
    """Versão async de `extract_with_retry`; mesma regra de retry e de soma de uso.

    O laço é duplicado de propósito (uma única diferença: `await`). Mudou a regra aqui, mude lá.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    total = Usage(0, 0)
    user = text
    last_error: InvalidOutputError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            completion = await _acall(client, user, model, max_completion_tokens)
            total = add_usage(total, completion.usage)
            value = _parse(completion)
        except InvalidOutputError as exc:
            last_error = exc
            user = with_feedback(text, exc)
            continue
        except ExtractionError as exc:
            exc.usage = total
            raise
        return ExtractionResult(value, total, attempt)

    raise InvalidOutputError(
        f"invalid output after {max_attempts} attempts: {last_error}", total
    ) from last_error


async def extract_many(
    client: AsyncLLMClient,
    texts: Sequence[str],
    *,
    model: str,
    max_concurrency: int = 5,
    max_attempts: int = 3,
) -> list[ExtractionResult | ExtractionError]:
    """Roda várias extrações juntas, no máximo `max_concurrency` ao mesmo tempo.

    Falha de um item volta como valor (não derruba os outros), para o custo de todos ser registrado.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")

    semaphore = asyncio.Semaphore(max_concurrency)

    async def one(text: str) -> ExtractionResult | ExtractionError:
        async with semaphore:
            try:
                return await aextract_with_retry(client, text, model=model, max_attempts=max_attempts)
            except ExtractionError as exc:
                return exc

    return list(await asyncio.gather(*(one(t) for t in texts)))


def _parse(completion: Completion) -> StockMessage:
    return parse_completion(completion, StockMessage)


def log_run_cost(result: ExtractionResult, model: str, table: PriceTable) -> Decimal | None:
    """Registra uma linha por execução e devolve o custo (`None` se o modelo não tem preço)."""
    cost = compute_cost(result.usage, table.models.get(model))
    if cost is None:
        logger.warning("no price for model=%s: cost unknown (total is a lower bound)", model)
    logger.info(
        "extraction model=%s attempts=%d prompt_tokens=%d completion_tokens=%d cost=%s %s prices_as_of=%s",
        model,
        result.attempts,
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        cost,
        table.currency,
        table.effective_date,
    )
    return cost
