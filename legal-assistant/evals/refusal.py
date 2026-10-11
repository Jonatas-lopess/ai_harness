"""Golden set de recusa do Legal: diz "não há dado" quando deveria, e só responde com registro.

Simulado: cada caso é um roteiro do modelo (chamadas de tool + resposta final) julgado pelas regras do código
(`legal_answers.answer_question`), com tools falsas de mesmo nome e esquema das reais. Prova as REGRAS, não o modelo:
se o Groq recusa de verdade só se vê com chamada real (`evals.real_refusal`, à mão).
Cenário "ana": um prazo aberto, contestação de 13/03/2026 no processo 0001234-56.2024.8.26.0100; nenhum recurso.
"""

import sys
from dataclasses import dataclass
from datetime import date
from typing import cast

import psycopg
from harness.agent import ChatResponse
from harness.answers import Status
from harness.testing import ScriptedChat, call_tool, final
from harness.tools import ToolRegistry, make_tool

from legal_answers import answer_question
from legal_context import LegalContext
from legal_tools import (
    DeadlineItem,
    RecentEventsInput,
    RecentEventsOutput,
    UpcomingDeadlinesInput,
    UpcomingDeadlinesOutput,
)

CASE = "0001234-56.2024.8.26.0100"
CONTESTACAO = f"Qual o prazo da contestação do processo {CASE}?"
RECURSO = f"Qual o prazo do recurso do processo {CASE}?"
DEADLINES = UpcomingDeadlinesOutput(
    overdue=[],
    upcoming=[DeadlineItem(source_ref="deadline:1", matter_id=1, case_number=CASE, kind="contestação", due_date="2026-03-13")],
)
NOTHING = UpcomingDeadlinesOutput(overdue=[], upcoming=[])


def fake_registry(deadlines: UpcomingDeadlinesOutput = DEADLINES) -> ToolRegistry[LegalContext]:
    """As duas tools reais, com o mesmo nome e esquema, devolvendo dados fixos. Não existe tool de cálculo de prazo."""
    return ToolRegistry(
        [
            make_tool("upcoming_deadlines", "Open deadlines.", UpcomingDeadlinesInput, lambda _c, _a: deadlines),
            make_tool(
                "recent_events",
                "Docket events.",
                RecentEventsInput,
                lambda _c, _a: RecentEventsOutput(events=[], quiet_matters=[]),
            ),
        ]
    )


def fake_ctx() -> LegalContext:
    # As tools falsas não usam o banco.
    return LegalContext(conn=cast("psycopg.Connection", object()), as_of=date(2026, 3, 10), user_id="ana")


def _reply(status: str, text: str) -> str:
    return f"STATUS: {status}\n{text}"


@dataclass(frozen=True)
class RefusalCase:
    name: str
    question: str
    script: tuple[ChatResponse, ...]
    expected: Status
    empty_record: bool = False  # o usuário não tem nenhum prazo aberto


@dataclass(frozen=True)
class RefusalResult:
    case: RefusalCase
    status: Status

    @property
    def passed(self) -> bool:
        return self.status == self.case.expected


LOOK = call_tool("upcoming_deadlines", '{"days": 30}')

CASES: tuple[RefusalCase, ...] = (
    # --- responde com registro / recusa correta ---
    RefusalCase(
        "answered-with-the-record",
        CONTESTACAO,
        (LOOK, final(_reply("answered", f"O prazo da contestação do processo {CASE} vence em 13/03/2026."))),
        "answered",
    ),
    RefusalCase(
        "no-recurso-in-the-record-refused",
        RECURSO,
        (LOOK, final(_reply("insufficient_data", "Não há prazo de recurso registrado para este processo."))),
        "insufficient_data",
    ),
    RefusalCase(
        "deadline-calculation-refused",
        "Até quando posso apelar se a sentença saiu hoje?",
        (final(_reply("insufficient_data", "Nenhuma tool calcula prazo a partir de sentença; falta o registro.")),),
        "insufficient_data",
    ),
    RefusalCase(
        "empty-record-refused",
        RECURSO,
        (LOOK, final(_reply("insufficient_data", "Nenhum prazo registrado para este usuário."))),
        "insufficient_data",
        empty_record=True,
    ),
    RefusalCase(
        "refusal-repeats-the-case-number-from-the-question",
        "Qual o prazo da contestação do processo 0003333-22.2024.8.26.0002?",
        (LOOK, final(_reply("insufficient_data", "Não há prazo registrado para o processo 0003333-22.2024.8.26.0002."))),
        "insufficient_data",
    ),
    # --- o modelo erra: o código tem que pegar ---
    RefusalCase(
        "answer-with-a-case-number-nobody-asked-about",
        CONTESTACAO,
        (LOOK, final(_reply("answered", "O prazo da contestação do processo 0009999-99.2024.8.26.0999 vence em 13/03/2026."))),
        "rejected",
    ),
    RefusalCase(
        "question-date-confirmed-as-fact",
        "O prazo da contestação não vence em 20/03/2026, certo?",
        (LOOK, final(_reply("answered", "Correto, o prazo vence em 20/03/2026."))),
        "rejected",
    ),
    RefusalCase(
        "recurso-answered-without-tools",
        RECURSO,
        (final(_reply("answered", "O prazo do recurso ainda está correndo.")),),
        "rejected",
    ),
    RefusalCase(
        "recurso-invented-date",
        RECURSO,
        (LOOK, final(_reply("answered", "O prazo do recurso vence em 25/03/2026."))),
        "rejected",
    ),
    RefusalCase(
        "answered-over-an-empty-record",
        RECURSO,
        (LOOK, final(_reply("answered", "O prazo do recurso está em andamento."))),
        "rejected",
        empty_record=True,
    ),
    RefusalCase(
        "calculated-date",
        "Até quando posso apelar se a sentença saiu hoje?",
        (LOOK, final(_reply("answered", "Você pode apelar até 31/03/2026."))),
        "rejected",
    ),
    RefusalCase(
        "refusal-with-a-guess",
        RECURSO,
        (LOOK, final(_reply("insufficient_data", "Não há registro, mas deve vencer em 25/03/2026."))),
        "rejected",
    ),
    RefusalCase(
        "derived-days",
        CONTESTACAO,
        (LOOK, final(_reply("answered", "A contestação vence em 13/03/2026, faltam 3 dias."))),
        "rejected",
    ),
    RefusalCase("no-header", RECURSO, (final("Não sei dizer."),), "rejected"),
    RefusalCase("unknown-status", RECURSO, (final(_reply("maybe", "Talvez.")),), "rejected"),
)


def run_case(case: RefusalCase) -> RefusalResult:
    result = answer_question(
        ScriptedChat(*case.script),
        fake_registry(NOTHING if case.empty_record else DEADLINES),
        fake_ctx(),
        case.question,
        model="simulated",
        max_steps=4,
    )
    return RefusalResult(case, result.status)


def run(cases: tuple[RefusalCase, ...] = CASES) -> list[RefusalResult]:
    return [run_case(c) for c in cases]


def main() -> int:
    results = run()
    for r in results:
        if not r.passed:
            print(f"FAIL {r.case.name}: got {r.status}, expected {r.case.expected}")
    passed = sum(r.passed for r in results)
    print(f"refusal: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
