import logging
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from extract import ExtractionResult, Usage

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
