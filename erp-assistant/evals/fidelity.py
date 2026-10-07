"""Golden set de fidelidade: o texto só pode citar os fatos, cada número ligado ao seu campo.

Cada caso passa pelo caminho de produção (`explain`) com um cliente simulado que sempre devolve o
texto do caso. Aprovado = `explain` aceitou o texto. Reprovado esperado = `explain` degradou o item.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any

from extract import Completion, Usage
from refill_job import RefillFacts, explain

# F1: ruptura simples. F2: com pedido aberto. F3: números com separador de milhar. F4: do seed.
F1 = RefillFacts(
    product_id=1, name="Parafuso", on_hand=3, open_po_qty=0, reorder_point=40, suggested_qty=250
)
F2 = RefillFacts(
    product_id=2, name="Porca", on_hand=40, open_po_qty=30, reorder_point=105, suggested_qty=200
)
F3 = RefillFacts(
    product_id=3, name="Arruela", on_hand=1250, open_po_qty=0, reorder_point=2000, suggested_qty=800
)
F4 = RefillFacts(
    product_id=1, name="rupture", on_hand=40, open_po_qty=0, reorder_point=105, suggested_qty=250
)
REAL_TEXT = "O estoque atual de 40 unidades está abaixo do ponto de reposição de 105 e não há pedidos em aberto (open_po_qty 0)."  # noqa: E501


@dataclass(frozen=True)
class FidelityCase:
    name: str
    facts: RefillFacts
    text: str
    expected_accepted: bool


@dataclass(frozen=True)
class FidelityResult:
    case: FidelityCase
    accepted: bool

    @property
    def passed(self) -> bool:
        return self.accepted == self.case.expected_accepted


CASES: tuple[FidelityCase, ...] = (
    # --- fiel: tem que ser aceito ---
    FidelityCase("basic", F1, "Estoque 3 abaixo do ponto 40; repor 250.", True),
    FidelityCase(
        "free-order",
        F1,
        "Repor 250 unidades: restam 3 em estoque, abaixo do ponto de reposição de 40.",
        True,
    ),
    FidelityCase("no-numbers", F1, "O estoque está baixo e precisa de reposição.", True),
    FidelityCase("number-before-label", F1, "3 unidades em estoque, ponto 40, repor 250.", True),
    FidelityCase(
        "open-po",
        F2,
        "Estoque 40 e pedido aberto de 30, abaixo do ponto de 105; repor 200.",
        True,
    ),
    FidelityCase("thousands-separator", F3, "Estoque 1.250, ponto 2.000; repor 800.", True),
    FidelityCase(
        "product-id-and-name",
        F1,
        "O produto 1 (Parafuso) tem estoque 3, abaixo do ponto 40.",
        True,
    ),
    # Texto real do Groq (gpt-oss-120b) que o primeiro validador reprovou por engano: o rótulo
    # seguinte ("pedidos") estava mais perto de 105 que o anterior ("ponto").
    FidelityCase("real-groq-open-po-sentence", F4, REAL_TEXT, True),
    # --- infiel: tem que ser rejeitado ---
    FidelityCase(
        "swap-on-hand-and-point", F1, "O estoque atual é 40, abaixo do ponto de 3; repor 250.", False
    ),
    FidelityCase("suggested-as-on-hand", F1, "Estoque 250; repor 3.", False),
    FidelityCase("point-as-suggested", F1, "Repor 40 unidades.", False),
    FidelityCase(
        "swap-on-hand-and-po", F2, "Estoque 30, pedido aberto de 40, ponto 105; repor 200.", False
    ),
    FidelityCase("number-before-label-swapped", F1, "250 unidades em estoque, ponto 40.", False),
    FidelityCase("invented-number", F1, "Repor 250; o fornecedor leva 12 dias.", False),
    FidelityCase("number-from-another-item", F1, "Repor 240.", False),
    FidelityCase("derived-sum", F2, "Estoque 40 mais pedido 30 dá 70.", False),
    FidelityCase("thousands-swapped", F3, "Estoque 2.000, ponto 1.250; repor 800.", False),
)


class _FixedClient:
    """Cliente simulado: responde sempre o mesmo texto, em todas as tentativas."""

    def __init__(self, text: str) -> None:
        self.text: str = text

    def complete(self, **_: Any) -> Completion:  # pyright: ignore[reportExplicitAny]
        return Completion(json.dumps({"rationale": self.text}), "stop", usage=Usage(0, 0))


def run_case(case: FidelityCase) -> FidelityResult:
    result = explain(_FixedClient(case.text), case.facts, model="simulated", max_attempts=1)
    return FidelityResult(case, accepted=result.rationale == case.text)


def run(cases: tuple[FidelityCase, ...] = CASES) -> list[FidelityResult]:
    return [run_case(c) for c in cases]


def main() -> int:
    results = run()
    for r in results:
        if not r.passed:
            verdict = "accepted" if r.accepted else "rejected"
            print(f"FAIL {r.case.name}: {verdict}, text={r.case.text!r}")
    passed = sum(r.passed for r in results)
    print(f"fidelity: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
