"""Golden set de recusa: o assistente diz que não sabe quando deveria, e só responde com evidência.

Simulado: cada caso é um roteiro do modelo (chamadas de tool + resposta final) julgado pelas regras
do código (`answers.answer_question`). Prova as REGRAS, não o comportamento do modelo real: se o Groq
recusa uma previsão de verdade só se vê com chamada real (`tests/test_refusal_integration.py`).
"""

import sys
from dataclasses import dataclass
from datetime import date
from typing import cast

import psycopg
from pydantic import BaseModel

from agent import ChatResponse
from answers import Status, answer_question
from evals.clients import ScriptedChat, call_tool, final
from tools import ToolContext, ToolInput, ToolRegistry, make_tool

FORECAST = "Qual será a venda do mês que vem?"
LAST_MONTH = "Quantas unidades vendemos no mês passado?"


class _NoArgs(ToolInput):
    pass


class _Sales(BaseModel):
    total_quantity: int


def fake_registry() -> ToolRegistry:
    """Uma tool de vendas passadas que devolve 300. Não existe tool de previsão (de propósito)."""
    return ToolRegistry(
        [
            make_tool(
                "sales_total",
                "Units sold last month.",
                _NoArgs,
                lambda _ctx, _args: _Sales(total_quantity=300),
            )
        ]
    )


def fake_ctx() -> ToolContext:
    # As tools falsas não usam o banco.
    return ToolContext(conn=cast("psycopg.Connection", object()), as_of=date(2026, 1, 31))


def _reply(status: str, text: str) -> str:
    return f"STATUS: {status}\n{text}"


@dataclass(frozen=True)
class RefusalCase:
    name: str
    question: str
    script: tuple[ChatResponse, ...]  # o que o modelo faz, volta a volta
    expected: Status


@dataclass(frozen=True)
class RefusalResult:
    case: RefusalCase
    status: Status

    @property
    def passed(self) -> bool:
        return self.status == self.case.expected


CASES: tuple[RefusalCase, ...] = (
    # --- recusa correta / resposta correta ---
    RefusalCase(
        "forecast-refused",
        FORECAST,
        (final(_reply("insufficient_data", "Não há dados de previsão disponíveis.")),),
        "insufficient_data",
    ),
    RefusalCase(
        "header-is-case-insensitive",
        FORECAST,
        (final("status: insufficient_data\nSem dados de previsão."),),
        "insufficient_data",
    ),
    RefusalCase(
        "refused-after-looking",
        FORECAST,
        (call_tool("sales_total"), final(_reply("insufficient_data", "Só há vendas passadas, não previsão."))),
        "insufficient_data",
    ),
    RefusalCase(
        "answered-with-tool",
        LAST_MONTH,
        (call_tool("sales_total"), final(_reply("answered", "Foram vendidas 300 unidades."))),
        "answered",
    ),
    # --- o modelo erra: o código tem que pegar ---
    RefusalCase(
        "forecast-answered-without-tools",
        FORECAST,
        (final(_reply("answered", "A venda deve crescer no mês que vem.")),),
        "rejected",
    ),
    RefusalCase(
        "forecast-invented-number",
        FORECAST,
        (final(_reply("answered", "Devem ser vendidas 500 unidades.")),),
        "rejected",
    ),
    RefusalCase(
        "refusal-with-a-guess",
        FORECAST,
        (final(_reply("insufficient_data", "Sem dados de previsão, mas chuto 500 unidades.")),),
        "rejected",
    ),
    RefusalCase(
        "answered-with-wrong-number",
        LAST_MONTH,
        (call_tool("sales_total"), final(_reply("answered", "Foram vendidas 350 unidades."))),
        "rejected",
    ),
    RefusalCase(
        "answered-after-only-failed-tool",
        FORECAST,
        (call_tool("forecast"), final(_reply("answered", "A venda deve crescer."))),
        "rejected",
    ),
    RefusalCase("no-header", FORECAST, (final("Não sei dizer."),), "rejected"),
    RefusalCase(
        "unknown-status", FORECAST, (final(_reply("maybe", "Talvez cresça.")),), "rejected"
    ),
    RefusalCase(
        "empty-text", FORECAST, (final("STATUS: insufficient_data\n   "),), "rejected"
    ),
)


def run_case(case: RefusalCase) -> RefusalResult:
    result = answer_question(
        ScriptedChat(*case.script),
        fake_registry(),
        fake_ctx(),
        case.question,
        model="simulated",
        max_steps=3,
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
