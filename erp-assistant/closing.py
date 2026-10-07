"""Fechamento do dia: o SQL agrega, o código decide os números; o LLM só narra (closing_job)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg
from psycopg.rows import class_row
from pydantic import BaseModel

# Preço = `products.price` ATUAL: o schema não guarda o preço no momento da venda.
_TOTALS_SQL = """
SELECT
    COALESCE(SUM(s.quantity * p.price), 0) AS revenue,
    COALESCE(SUM(s.quantity), 0)::int AS units
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE s.sale_date = %(day)s
"""

_TOP_PRODUCT_SQL = """
SELECT p.name AS top_product
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE s.sale_date = %(day)s
GROUP BY p.id, p.name
ORDER BY SUM(s.quantity * p.price) DESC, p.id
LIMIT 1
"""


@dataclass(frozen=True)
class _TotalsRow:
    revenue: Decimal
    units: int


@dataclass(frozen=True)
class _TopRow:
    top_product: str


class ClosingFacts(BaseModel):
    """Tudo que o modelo pode citar sobre o dia. Vem do código; número fora daqui reprova o texto."""

    day: date
    revenue: Decimal
    units: int
    top_product: str  # produto de maior faturamento do dia

    def labelled_values(self) -> dict[str, int | Decimal]:
        return {"revenue": self.revenue, "units": self.units}


def closing_facts(conn: psycopg.Connection, day: date) -> ClosingFacts | None:
    """Fatos do dia, ou None se não houve venda (nada a narrar: o código decide, sem chamar o LLM)."""
    with conn.cursor(row_factory=class_row(_TotalsRow)) as cur:
        totals = cur.execute(_TOTALS_SQL, {"day": day}).fetchone()
    if totals is None or totals.units == 0:
        return None
    with conn.cursor(row_factory=class_row(_TopRow)) as cur:
        top = cur.execute(_TOP_PRODUCT_SQL, {"day": day}).fetchone()
    if top is None:
        return None
    return ClosingFacts(
        day=day, revenue=totals.revenue, units=totals.units, top_product=top.top_product
    )
