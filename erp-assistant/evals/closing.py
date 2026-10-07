"""Golden set de fidelidade do resumo de fechamento: total conhecido, texto só cita os fatos.

Mesmo desenho de `evals.fidelity`: cada caso passa por `narrate_closing` (caminho de produção) com
um cliente simulado que devolve o texto do caso. Dia 2026-01-20 do seed: 4 vendas, R$ 10.950,00,
465 unidades, maior faturamento `received-po`.
"""

import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from closing import ClosingFacts
from closing_job import narrate_closing
from evals.clients import FixedClient

FACTS = ClosingFacts(
    day=date(2026, 1, 20), revenue=Decimal("10950.00"), units=465, top_product="received-po"
)


@dataclass(frozen=True)
class ClosingCase:
    name: str
    text: str
    expected_accepted: bool


@dataclass(frozen=True)
class ClosingResult:
    case: ClosingCase
    accepted: bool

    @property
    def passed(self) -> bool:
        return self.accepted == self.case.expected_accepted


CASES: tuple[ClosingCase, ...] = (
    # --- fiel: tem que ser aceito ---
    ClosingCase(
        "basic", "Faturamento de R$ 10.950,00 com 465 unidades vendidas; destaque para received-po.", True
    ),
    ClosingCase("total-first", "Total de R$ 10.950,00 em 465 unidades, com destaque para received-po.", True),
    ClosingCase("pt-br-without-cents", "O dia fechou em R$ 10.950 com 465 unidades.", True),
    ClosingCase("dot-decimal", "Faturamento de R$ 10950.00 e 465 unidades.", True),
    ClosingCase("comma-decimal-no-thousands", "Faturamento de R$ 10950,00 e 465 unidades.", True),
    ClosingCase("mentions-the-date", "Em 20/01/2026, faturamos R$ 10.950,00.", True),
    ClosingCase("number-before-label", "Foram vendidas 465 unidades, com faturamento de R$ 10.950,00.", True),
    ClosingCase("no-numbers", "O produto de maior faturamento foi received-po.", True),
    # Texto real do Groq (gpt-oss-120b): copia o valor literal, sem formatar em pt-BR.
    ClosingCase(
        "real-groq-verbatim",
        "O faturamento foi 10950.00 e foram vendidas 465 unidades, sendo o produto de maior faturamento received-po.",
        True,
    ),
    # --- infiel: tem que ser rejeitado ---
    ClosingCase("wrong-total", "Faturamento de R$ 10.590,00 com 465 unidades.", False),
    ClosingCase("wrong-units", "Faturamento de R$ 10.950,00 com 456 unidades.", False),
    ClosingCase("rounded-total", "Faturamento de cerca de R$ 11 mil com 465 unidades.", False),
    ClosingCase("swapped-fields", "Foram 10.950 unidades e faturamento de R$ 465,00.", False),
    ClosingCase("swapped-fields-label-first", "Faturamento de 465 com 10.950 unidades.", False),
    ClosingCase("invented-growth", "Faturamento de R$ 10.950,00, 12% acima do dia anterior.", False),
    ClosingCase("invented-forecast", "Faturamento de R$ 10.950,00; deve chegar a R$ 12.000,00 amanhã.", False),
    ClosingCase("number-from-another-day", "Faturamento de R$ 10.950,00 com 999 unidades.", False),
)


def run_case(case: ClosingCase) -> ClosingResult:
    result = narrate_closing(FixedClient(case.text), FACTS, model="simulated", max_attempts=1)
    return ClosingResult(case, accepted=result.rationale == case.text)


def run(cases: tuple[ClosingCase, ...] = CASES) -> list[ClosingResult]:
    return [run_case(c) for c in cases]


def main() -> int:
    results = run()
    for r in results:
        if not r.passed:
            verdict = "accepted" if r.accepted else "rejected"
            print(f"FAIL {r.case.name}: {verdict}, text={r.case.text!r}")
    passed = sum(r.passed for r in results)
    print(f"closing: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
