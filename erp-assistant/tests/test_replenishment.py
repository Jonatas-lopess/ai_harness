from datetime import date

import psycopg
from pytest import mark

from replenishment import (
    low_stock,
    needs_refill,
    refill_target,
    reorder_point,
    stock_positions,
    suggested_qty,
)
from settings import get_settings

AS_OF = date(2026, 1, 31)


@mark.parametrize(
    ("on_hand", "open_po_qty", "point", "expected"),
    [
        (20, 0, 40, True),
        (20, 50, 40, False),  # pedido aberto cobre: sem falso alarme
        (100, 0, 40, False),
        (40, 0, 40, False),  # igual ao ponto não sinaliza (só abaixo)
        (39, 0, 40, True),
    ],
)
def test_needs_refill(on_hand: int, open_po_qty: int, point: int, expected: bool):
    assert needs_refill(on_hand, open_po_qty, point) is expected


def test_reorder_point_scales_with_lead_time():
    assert reorder_point(300, 30, 5, 5) == 55
    assert reorder_point(300, 30, 30, 5) == 305


def test_reorder_point_rounds_up():
    # 10 vendas / 30 dias * 5 dias = 1,67 -> 2
    assert reorder_point(10, 30, 5, 0) == 2


def test_reorder_point_exact_division_does_not_round_up():
    # com float, (31 / 30) * 30 = 31.000000000000004 e o teto daria 32
    assert reorder_point(31, 30, 30, 0) == 31


def test_reorder_point_without_sales_is_safety_stock():
    assert reorder_point(0, 30, 10, 7) == 7


def test_refill_target_adds_cover_days_of_demand():
    # 300 vendas em 30 dias = 10/dia; 15 dias de cobertura = 150
    assert refill_target(105, 300, 30, 15) == 255


@mark.parametrize(
    ("on_hand", "open_po_qty", "target", "multiple", "expected"),
    [
        (40, 0, 255, 50, 250),  # falta 215 -> sobe ao múltiplo de 50
        (40, 0, 240, 50, 200),  # falta 200, já é múltiplo: não arredonda a mais
        (40, 100, 255, 50, 150),  # pedido aberto entra na posição
        (40, 0, 255, 1, 215),  # sem múltiplo, é a falta exata
        (300, 0, 255, 50, 0),  # acima do alvo: nada a pedir
        (255, 0, 255, 50, 0),  # exatamente no alvo: nada a pedir
    ],
)
def test_suggested_qty(on_hand: int, open_po_qty: int, target: int, multiple: int, expected: int):
    assert suggested_qty(on_hand, open_po_qty, target, multiple) == expected


@mark.integration
def test_stock_positions_from_seed():
    with psycopg.connect(get_settings().database_url.get_secret_value()) as conn:
        positions = {p.name: p for p in stock_positions(conn, AS_OF)}

    assert positions["rupture"].reorder_point == 105
    assert positions["rupture"].open_po_qty == 0  # pedido cancelado não conta
    assert positions["covered-by-po"].open_po_qty == 100
    assert positions["received-po"].open_po_qty == 0  # pedido recebido já está no estoque
    # vendas fora da janela (2025-12-01 e a do próprio as_of) não entram na demanda
    assert positions["false-alarm"].reorder_point == 7
    # alvo 255, posição 40: falta 215 -> 250 (múltiplo 50) e 240 (múltiplo 30)
    assert positions["rupture"].suggested_qty == 250
    assert positions["received-po"].suggested_qty == 240
    # sem sinal, sem quantidade
    assert positions["covered-by-po"].suggested_qty == 0
    assert positions["false-alarm"].suggested_qty == 0


@mark.integration
def test_low_stock_flags_only_real_needs():
    with psycopg.connect(get_settings().database_url.get_secret_value()) as conn:
        flagged = {p.name for p in low_stock(conn, AS_OF)}

    assert flagged == {"rupture", "received-po"}
