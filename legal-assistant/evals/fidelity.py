"""Golden set de fidelidade da frase do digest: a data e o processo do texto são os do registro, nada mais.

Cada caso passa por `build_digest` (caminho de produção) com um cliente simulado que devolve o texto do caso, uma
tentativa só: o que se mede é o validador, não o modelo. O que o modelo real faz está em `evals.real_digest` (à mão).
Linha `upcoming`: contestação, 2026-03-13, processo 0001234-56.2024.8.26.0100.
Linha `overdue`: manifestação sobre laudo, 2026-03-02, processo 0007654-32.2023.8.26.0050.
"""

import sys
from dataclasses import dataclass
from typing import Literal

from harness.testing import FixedClient

from legal_digest import build_digest
from legal_tools import DeadlineItem, UpcomingDeadlinesOutput

UPCOMING = DeadlineItem(
    source_ref="deadline:1",
    matter_id=1,
    case_number="0001234-56.2024.8.26.0100",
    kind="contestação",
    due_date="2026-03-13",
)
OVERDUE = DeadlineItem(
    source_ref="deadline:3",
    matter_id=2,
    case_number="0007654-32.2023.8.26.0050",
    kind="manifestação sobre laudo",
    due_date="2026-03-02",
)


@dataclass(frozen=True)
class FidelityCase:
    name: str
    text: str
    expected_accepted: bool
    row: Literal["upcoming", "overdue"] = "upcoming"


@dataclass(frozen=True)
class FidelityResult:
    case: FidelityCase
    accepted: bool

    @property
    def passed(self) -> bool:
        return self.accepted == self.case.expected_accepted


CASES: tuple[FidelityCase, ...] = (
    # --- fiel: tem que ser aceito ---
    FidelityCase("basic", "O prazo de contestação vence em 13/03/2026 (processo 0001234-56.2024.8.26.0100).", True),
    FidelityCase("iso-date", "Contestação com vencimento em 2026-03-13, processo 0001234-56.2024.8.26.0100.", True),
    FidelityCase("written-out-date", "O prazo de contestação vence em 13 de março de 2026.", True),
    FidelityCase("written-out-date-no-accent", "O prazo de contestação vence em 13 de Marco de 2026.", True),
    FidelityCase("number-first", "Processo nº 0001234-56.2024.8.26.0100: contestação até 13/03/2026.", True),
    FidelityCase(
        "overdue-basic",
        "O prazo de manifestação sobre laudo venceu em 02/03/2026 e continua aberto (processo 0007654-32.2023.8.26.0050).",
        True,
        "overdue",
    ),
    # Textos reais do Groq (gpt-oss-120b) na primeira chamada real da fase 6.
    FidelityCase(
        "real-groq-overdue",
        "Manifestação sobre laudo com vencimento em 02/03/2026, processo 0007654-32.2023.8.26.0050, prazo já venceu e continua aberto.",
        True,
        "overdue",
    ),
    FidelityCase("real-groq-upcoming", "Contestação com vencimento em 13/03/2026, processo nº 0001234-56.2024.8.26.0100.", True),
    # --- infiel: tem que ser rejeitado ---
    FidelityCase("wrong-day", "O prazo de contestação vence em 14/03/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("wrong-month", "O prazo de contestação vence em 13/04/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("wrong-year", "O prazo de contestação vence em 13/03/2027 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("day-and-month-swapped", "O prazo de contestação vence em 03/13/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("impossible-date", "O prazo de contestação vence em 31/02/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("date-of-another-deadline", "O prazo de contestação vence em 02/04/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("date-of-the-other-row", "O prazo de contestação vence em 02/03/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("wrong-kind", "O prazo de recurso vence em 13/03/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("omits-the-kind", "Há um prazo em 13/03/2026 (processo 0001234-56.2024.8.26.0100).", False),
    FidelityCase("two-dates-one-wrong", "O prazo de contestação vence em 13/03/2026, ou 14/03/2026.", False),
    FidelityCase("wrong-case-digit", "O prazo de contestação vence em 13/03/2026 (processo 0001234-56.2024.8.26.0101).", False),
    FidelityCase("case-of-another-matter", "O prazo de contestação vence em 13/03/2026 (processo 0007654-32.2023.8.26.0050).", False),
    FidelityCase("derived-days", "O prazo de contestação vence em 13/03/2026; faltam 3 dias.", False),
    FidelityCase("invented-extension", "O prazo de contestação foi prorrogado para 20/03/2026.", False),
    FidelityCase("forged-ref", "O prazo de contestação vence em 13/03/2026 (deadline:17).", False),
    FidelityCase("wrong-written-out-date", "O prazo de contestação vence em 14 de março de 2026.", False),
    FidelityCase("impossible-written-out-date", "O prazo de contestação vence em 31 de fevereiro de 2026.", False),
)


def _output(row: Literal["upcoming", "overdue"]) -> UpcomingDeadlinesOutput:
    if row == "overdue":
        return UpcomingDeadlinesOutput(overdue=[OVERDUE], upcoming=[])
    return UpcomingDeadlinesOutput(overdue=[], upcoming=[UPCOMING])


def run_case(case: FidelityCase) -> FidelityResult:
    digest = build_digest(FixedClient(case.text), _output(case.row), model="simulated", max_attempts=1)
    return FidelityResult(case, accepted=digest.items[0].sentence == case.text)


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
