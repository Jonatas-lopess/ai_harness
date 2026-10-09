"""Custo por chamada e por job: mecanismo genérico. A tabela de preços é do pack e chega pela borda.

`costed_span(..., prices=tabela)` define a tabela da execução (uma `ContextVar`, como o trace atual).
Sem tabela, o custo fica `None` e o job sai com `cost_complete=False`: visível, nunca um número inventado.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from harness.llm import Usage
from harness.tracing import Span, current_trace, descendants, span

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


_prices: ContextVar[PriceTable | None] = ContextVar("harness_prices", default=None)


def load_prices(path: Path) -> PriceTable:
    return PriceTable.model_validate_json(path.read_text(encoding="utf-8"))


def compute_cost(usage: Usage, price: Price | None) -> Decimal | None:
    """Custo na moeda da tabela, ou `None` se o modelo não tem preço cadastrado."""
    if price is None:
        return None
    return (
        usage.prompt_tokens * price.input_per_mtok
        + usage.completion_tokens * price.output_per_mtok
    ) / TOKENS_PER_MTOK


def usage_attributes(usage: Usage | None, model: str, table: PriceTable | None = None) -> dict[str, object]:
    """Tokens e custo de UMA chamada, para gravar no span na hora. O preço vigente fica congelado no trace:
    recalcular na leitura reescreveria o custo histórico com o preço novo."""
    table = table or _prices.get()
    cost = compute_cost(usage, table.models.get(model)) if usage is not None and table is not None else None
    return {
        "prompt_tokens": usage.prompt_tokens if usage is not None else None,
        "completion_tokens": usage.completion_tokens if usage is not None else None,
        "cost": cost,
        "currency": table.currency if table is not None else None,
        "prices_as_of": table.effective_date if table is not None else None,
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
def costed_span(
    name: str, /, *, prices: PriceTable | None = None, **attributes: object
) -> Generator[Span]:
    """Span de job: ao sair, mesmo com exceção, grava o custo dos `llm_call` abaixo dele. Falha também gasta.

    `prices` vale para tudo dentro do job; sem ele, herda a tabela do job pai (se houver).
    """
    token = _prices.set(prices) if prices is not None else None
    with span(name, **attributes) as job:
        try:
            yield job
        finally:
            if token is not None:
                _prices.reset(token)
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
