from dataclasses import dataclass
from datetime import date, timedelta

import psycopg
from psycopg.rows import class_row

DEFAULT_WINDOW_DAYS = 30

# Agregações no SQL; a regra de negócio fica em Python puro (testável sem banco).
# Subconsultas em vez de JOIN com vendas e pedidos: dois JOINs multiplicariam linhas.
_POSITIONS_SQL = """
SELECT
    p.id AS product_id,
    p.name,
    p.stock AS on_hand,
    p.safety_stock,
    s.lead_time_days,
    COALESCE((
        SELECT SUM(quantity) FROM sales
        WHERE product_id = p.id AND sale_date >= %(start)s AND sale_date < %(as_of)s
    ), 0) AS sold_in_window,
    COALESCE((
        SELECT SUM(quantity) FROM purchase_orders
        WHERE product_id = p.id AND status = 'open'
    ), 0) AS open_po_qty
FROM products p
JOIN suppliers s ON s.id = p.supplier_id
ORDER BY p.id
"""


@dataclass(frozen=True)
class _PositionRow:
    """Uma linha do SQL; os campos têm o mesmo nome das colunas (`class_row` monta por nome)."""

    product_id: int
    name: str
    on_hand: int
    safety_stock: int
    lead_time_days: int
    sold_in_window: int
    open_po_qty: int


@dataclass(frozen=True)
class StockPosition:
    product_id: int
    name: str
    on_hand: int
    open_po_qty: int
    reorder_point: int
    needs_refill: bool


def reorder_point(
    sold_in_window: int, window_days: int, lead_time_days: int, safety_stock: int
) -> int:
    """Demanda esperada durante o prazo do fornecedor + estoque de segurança, arredondada para cima."""
    # Divisão inteira com teto: `/` devolveria float e (31 / 30) * 30 dá 31.000000000000004.
    expected_demand = -(-(sold_in_window * lead_time_days) // window_days)
    return expected_demand + safety_stock


def needs_refill(on_hand: int, open_po_qty: int, reorder_point: int) -> bool:
    return on_hand + open_po_qty < reorder_point


def stock_positions(
    conn: psycopg.Connection, as_of: date, window_days: int = DEFAULT_WINDOW_DAYS
) -> list[StockPosition]:
    params = {"as_of": as_of, "start": as_of - timedelta(days=window_days)}
    with conn.cursor(row_factory=class_row(_PositionRow)) as cur:
        rows = cur.execute(_POSITIONS_SQL, params).fetchall()
    positions: list[StockPosition] = []
    for row in rows:
        point = reorder_point(
            row.sold_in_window, window_days, row.lead_time_days, row.safety_stock
        )
        positions.append(
            StockPosition(
                product_id=row.product_id,
                name=row.name,
                on_hand=row.on_hand,
                open_po_qty=row.open_po_qty,
                reorder_point=point,
                needs_refill=needs_refill(row.on_hand, row.open_po_qty, point),
            )
        )
    return positions


def low_stock(
    conn: psycopg.Connection, as_of: date, window_days: int = DEFAULT_WINDOW_DAYS
) -> list[StockPosition]:
    return [p for p in stock_positions(conn, as_of, window_days) if p.needs_refill]
