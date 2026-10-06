"""Golden set de detecção: grupos `detection` (deve sinalizar) e `false_alarm` (não deve).

Os valores esperados foram calculados à mão, não pela função testada. Fórmulas:
  ponto = ceil(vendas * prazo / janela) + segurança
  alvo  = ponto + ceil(vendas * cobertura / janela)
  sinaliza se estoque + pedido aberto < ponto
  qtd   = ceil((alvo - (estoque + pedido)) / múltiplo) * múltiplo
"""

import sys
from dataclasses import dataclass
from typing import Literal

from replenishment import PositionRow, position_from_row

Group = Literal["detection", "false_alarm"]


@dataclass(frozen=True)
class Case:
    name: str
    on_hand: int
    open_po_qty: int
    sold_in_window: int
    lead_time_days: int
    safety_stock: int
    order_multiple: int
    expected_flagged: bool
    expected_qty: int  # 0 quando não sinaliza
    window_days: int = 30
    cover_days: int = 15

    @property
    def group(self) -> Group:
        return "detection" if self.expected_flagged else "false_alarm"


@dataclass(frozen=True)
class CaseResult:
    case: Case
    flagged: bool
    qty: int

    @property
    def passed(self) -> bool:
        return self.flagged == self.case.expected_flagged and self.qty == self.case.expected_qty


# Base: 300 vendas/30 dias (10/dia), prazo 10, segurança 5 => ponto 105, alvo 255.
CASES: tuple[Case, ...] = (
    # --- detecção correta ---
    Case("rupture", 40, 0, 300, 10, 5, 50, True, 250),  # falta 215 -> 5 caixas
    Case("zero-stock", 0, 0, 300, 10, 5, 50, True, 300),  # falta 255 -> 6 caixas
    Case("one-below-point", 104, 0, 300, 10, 5, 50, True, 200),  # falta 151 -> 4 caixas
    Case("one-below-point-with-po", 60, 44, 300, 10, 5, 50, True, 200),  # 104 no total
    Case("multiple-of-one", 40, 0, 300, 10, 5, 1, True, 215),
    Case("multiple-of-100", 40, 0, 300, 10, 5, 100, True, 300),  # falta 215 -> 3 lotes
    Case("shortfall-exact-multiple", 5, 0, 300, 10, 5, 50, True, 250),  # falta 250 = 5 caixas
    Case("po-too-small", 40, 30, 300, 10, 5, 50, True, 200),  # falta 185 -> 4 caixas
    Case("fast-supplier", 10, 0, 150, 5, 0, 10, True, 90),  # ponto 25, alvo 100
    Case("ceil-in-reorder-point", 5, 0, 31, 10, 0, 1, True, 22),  # ponto 11, alvo 27
    Case("safety-stock-only", 10, 0, 0, 10, 20, 10, True, 10),  # sem vendas: ponto = segurança
    Case("no-cover-days", 40, 0, 300, 10, 5, 1, True, 65, cover_days=0),  # alvo = ponto
    Case("window-15-days", 40, 0, 150, 10, 5, 50, True, 250, window_days=15),
    # --- falso alarme ---
    Case("covered-by-po", 40, 100, 300, 10, 5, 50, False, 0),
    Case("exactly-at-point-with-po", 60, 45, 300, 10, 5, 50, False, 0),  # 105: só abaixo sinaliza
    Case("exactly-at-point-no-po", 105, 0, 300, 10, 5, 50, False, 0),
    Case("po-covers-all", 0, 105, 300, 10, 5, 50, False, 0),
    Case("po-overshoot", 0, 500, 300, 10, 5, 50, False, 0),
    Case("plenty-of-stock", 1000, 0, 300, 10, 5, 50, False, 0),
    Case("low-sales-big-stock", 100, 0, 30, 5, 2, 1, False, 0),  # ponto 7
    Case("zero-stock-zero-demand", 0, 0, 0, 10, 0, 1, False, 0),  # ponto 0: nada a repor
    Case("no-sales-safety-met", 20, 0, 0, 10, 20, 10, False, 0),
    Case("ceil-boundary-at-point", 11, 0, 31, 10, 0, 1, False, 0),  # ponto 11
    Case("fast-supplier-at-point", 25, 0, 150, 5, 0, 10, False, 0),
)


def run_case(case: Case) -> CaseResult:
    row = PositionRow(
        product_id=1,
        name=case.name,
        on_hand=case.on_hand,
        safety_stock=case.safety_stock,
        order_multiple=case.order_multiple,
        lead_time_days=case.lead_time_days,
        sold_in_window=case.sold_in_window,
        open_po_qty=case.open_po_qty,
    )
    position = position_from_row(row, case.window_days, case.cover_days)
    return CaseResult(case, position.needs_refill, position.suggested_qty)


def run(cases: tuple[Case, ...] = CASES) -> list[CaseResult]:
    return [run_case(c) for c in cases]


def score_by_group(results: list[CaseResult]) -> dict[str, tuple[int, int]]:
    """Grupo -> (passou, total)."""
    out: dict[str, tuple[int, int]] = {}
    for r in results:
        passed, total = out.get(r.case.group, (0, 0))
        out[r.case.group] = (passed + r.passed, total + 1)
    return out


def main() -> int:
    results = run()
    for r in results:
        if not r.passed:
            c = r.case
            got = f"flagged={r.flagged} qty={r.qty}"
            want = f"flagged={c.expected_flagged} qty={c.expected_qty}"
            print(f"FAIL {c.name}: {got} (expected {want})")
    for group, (passed, total) in score_by_group(results).items():
        print(f"{group}: {passed}/{total}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
