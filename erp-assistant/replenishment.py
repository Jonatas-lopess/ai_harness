from dataclasses import dataclass
from datetime import date, timedelta

import psycopg
from psycopg.rows import class_row

DEFAULT_WINDOW_DAYS = 30
# Dias de venda que um pedido cobre além do ponto de reposição (política, não derivado).
DEFAULT_COVER_DAYS = 15

# Agregações no SQL; a regra de negócio fica em Python puro (testável sem banco).
# Subconsultas em vez de JOIN com vendas e pedidos: dois JOINs multiplicariam linhas.
_POSITIONS_SQL = """
SELECT
    p.id AS product_id,
    p.name,
    p.stock AS on_hand,
    p.safety_stock,
    p.order_multiple,
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
class PositionRow:
    """Uma linha do SQL; os campos têm o mesmo nome das colunas (`class_row` monta por nome)."""

    product_id: int
    name: str
    on_hand: int
    safety_stock: int
    order_multiple: int
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
    suggested_qty: int


def _ceil_div(numerator: int, denominator: int) -> int:
    """Divisão inteira com teto: `/` devolveria float e (31 / 30) * 30 dá 31.000000000000004."""
    return -(-numerator // denominator)


def reorder_point(
    sold_in_window: int, window_days: int, lead_time_days: int, safety_stock: int
) -> int:
    """Demanda esperada durante o prazo do fornecedor + estoque de segurança, arredondada para cima."""
    return _ceil_div(sold_in_window * lead_time_days, window_days) + safety_stock


def needs_refill(on_hand: int, open_po_qty: int, reorder_point: int) -> bool:
    return on_hand + open_po_qty < reorder_point


def refill_target(
    reorder_point: int, sold_in_window: int, window_days: int, cover_days: int
) -> int:
    """Nível alvo: ponto de reposição + `cover_days` de demanda. A folga evita pedir só até o ponto
    (estoque chegaria rente ao ponto e o job sinalizaria de novo no dia seguinte)."""
    return reorder_point + _ceil_div(sold_in_window * cover_days, window_days)


def suggested_qty(on_hand: int, open_po_qty: int, target: int, order_multiple: int) -> int:
    """Quanto falta para o alvo, descontando o que já está a caminho, arredondado PARA CIMA ao
    múltiplo do fornecedor. Sem falta, 0."""
    shortfall = target - (on_hand + open_po_qty)
    if shortfall <= 0:
        return 0
    return _ceil_div(shortfall, order_multiple) * order_multiple


def position_from_row(row: PositionRow, window_days: int, cover_days: int) -> StockPosition:
    """Regra de negócio pura sobre uma linha agregada: o SQL só agrega, a decisão é daqui."""
    point = reorder_point(row.sold_in_window, window_days, row.lead_time_days, row.safety_stock)
    refill = needs_refill(row.on_hand, row.open_po_qty, point)
    target = refill_target(point, row.sold_in_window, window_days, cover_days)
    return StockPosition(
        product_id=row.product_id,
        name=row.name,
        on_hand=row.on_hand,
        open_po_qty=row.open_po_qty,
        reorder_point=point,
        needs_refill=refill,
        suggested_qty=(
            suggested_qty(row.on_hand, row.open_po_qty, target, row.order_multiple)
            if refill
            else 0
        ),
    )


def stock_positions(
    conn: psycopg.Connection,
    as_of: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cover_days: int = DEFAULT_COVER_DAYS,
) -> list[StockPosition]:
    params = {"as_of": as_of, "start": as_of - timedelta(days=window_days)}
    with conn.cursor(row_factory=class_row(PositionRow)) as cur:
        rows = cur.execute(_POSITIONS_SQL, params).fetchall()
    return [position_from_row(row, window_days, cover_days) for row in rows]


def low_stock(
    conn: psycopg.Connection,
    as_of: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cover_days: int = DEFAULT_COVER_DAYS,
) -> list[StockPosition]:
    return [p for p in stock_positions(conn, as_of, window_days, cover_days) if p.needs_refill]
