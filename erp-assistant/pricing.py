import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from extract import ExtractionResult, Usage
from tracing import Span, current_trace, descendants, span

logger = logging.getLogger(__name__)

DEFAULT_PRICES_PATH = Path(__file__).parent / "prices.json"
TOKENS_PER_MTOK = Decimal(1_000_000)


class Price(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    input_per_mtok: Decimal
    output_per_mtok: Decimal


class PriceTable(BaseModel):
    """Preços versionados em arquivo, com fonte e data de vigência."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    source: str
    effective_date: str
    currency: str
    models: dict[str, Price]


def load_prices(path: Path = DEFAULT_PRICES_PATH) -> PriceTable:
    return PriceTable.model_validate_json(path.read_text(encoding="utf-8"))


def compute_cost(usage: Usage, price: Price | None) -> Decimal | None:
    """Custo na moeda da tabela, ou `None` se o modelo não tem preço cadastrado."""
    if price is None:
        return None
    return (
        usage.prompt_tokens * price.input_per_mtok
        + usage.completion_tokens * price.output_per_mtok
    ) / TOKENS_PER_MTOK


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


@lru_cache(maxsize=1)
def default_prices() -> PriceTable:
    return load_prices()


def usage_attributes(usage: Usage | None, model: str, table: PriceTable | None = None) -> dict[str, object]:
    """Tokens e custo de UMA chamada, para gravar no span na hora. O preço vigente fica congelado no trace:
    recalcular na leitura reescreveria o custo histórico com o preço novo."""
    table = table or default_prices()
    cost = compute_cost(usage, table.models.get(model)) if usage is not None else None
    return {
        "prompt_tokens": usage.prompt_tokens if usage is not None else None,
        "completion_tokens": usage.completion_tokens if usage is not None else None,
        "cost": cost,
        "currency": table.currency,
        "prices_as_of": table.effective_date,
    }


@dataclass(frozen=True)
class JobCost:
    cost: Decimal  # soma só das chamadas com preço: é piso, não total, quando `complete` é False
    complete: bool
    calls: int
    calls_without_cost: int
    prompt_tokens: int
    completion_tokens: int


def job_cost(spans: Sequence[Span]) -> JobCost:
    """Soma o custo dos spans `llm_call`. Chamada sem preço não entra na soma, mas é contada e marcada."""
    calls = [s for s in spans if s.name == "llm_call"]
    known = [c for c in (s.attributes.get("cost") for s in calls) if isinstance(c, Decimal)]
    return JobCost(
        cost=sum(known, Decimal(0)),
        complete=len(known) == len(calls),
        calls=len(calls),
        calls_without_cost=len(calls) - len(known),
        prompt_tokens=sum(_tokens(s, "prompt_tokens") for s in calls),
        completion_tokens=sum(_tokens(s, "completion_tokens") for s in calls),
    )


def _tokens(s: Span, key: str) -> int:
    value = s.attributes.get(key)
    return value if isinstance(value, int) else 0


@contextmanager
def costed_span(name: str, /, **attributes: object) -> Generator[Span]:
    """Span de job: ao sair, mesmo com exceção, grava o custo dos `llm_call` abaixo dele. Falha também gasta."""
    with span(name, **attributes) as job:
        try:
            yield job
        finally:
            trace = current_trace()
            summary = job_cost(descendants(trace, job.span_id) if trace else [])
            job.set(
                cost=summary.cost,
                cost_complete=summary.complete,
                llm_calls=summary.calls,
                calls_without_cost=summary.calls_without_cost,
                prompt_tokens=summary.prompt_tokens,
                completion_tokens=summary.completion_tokens,
            )
