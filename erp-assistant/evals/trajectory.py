"""Golden set de trajetória: o agente chamou as tools certas, em quantidade aceitável, dentro do orçamento?

Os outros evals olham o RESULTADO. Dois modelos podem dar a mesma resposta final, um com 1 tool call e
outro com 8: o segundo custa várias vezes mais e passa nos evals de resultado. Aqui se confere o CAMINHO.

Regra por tool: contagem entre `min` e `max`; tool fora da tabela é proibida. A ordem NÃO é conferida
de propósito: caminhos diferentes podem ser igualmente certos, e exigir ordem reprova os dois por um.
Simulado: cada caso é um roteiro do modelo; prova as REGRAS, não o comportamento do modelo real.
"""

import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from agent import BudgetExceededError, ChatResponse, ToolCallRecord, run_agent
from evals.clients import ScriptedChat, call_tool, final
from evals.refusal import fake_ctx
from tools import ToolInput, ToolRegistry, make_tool

QUESTION = "Quantas unidades vendemos no mês passado?"


class _NoArgs(ToolInput):
    pass


class _Sales(BaseModel):
    total_quantity: int


class _Stock(BaseModel):
    on_hand: int


def registry() -> ToolRegistry:
    return ToolRegistry(
        [
            make_tool("sales_total", "Units sold last month.", _NoArgs, lambda _c, _a: _Sales(total_quantity=300)),
            make_tool("stock_position", "Current stock.", _NoArgs, lambda _c, _a: _Stock(on_hand=12)),
        ]
    )


@dataclass(frozen=True)
class Bounds:
    min: int
    max: int


def violations(
    called: Sequence[str], limits: Mapping[str, Bounds], *, budget_exceeded: bool = False
) -> list[str]:
    """Códigos de violação, ordenados: `forbidden:t`, `missing:t`, `too_many:t`, `over_budget`."""
    counts = Counter(called)
    found = [f"forbidden:{t}" for t in counts if t not in limits]
    for tool, bounds in limits.items():
        if counts[tool] < bounds.min:
            found.append(f"missing:{tool}")
        elif counts[tool] > bounds.max:
            found.append(f"too_many:{tool}")
    if budget_exceeded:
        found.append("over_budget")
    return sorted(found)


@dataclass(frozen=True)
class TrajectoryCase:
    name: str
    script: tuple[ChatResponse, ...]  # o que o modelo faz, volta a volta
    limits: Mapping[str, Bounds]
    expected: tuple[str, ...]  # violações esperadas; vazio = trajetória limpa
    max_steps: int = 4


@dataclass(frozen=True)
class TrajectoryResult:
    case: TrajectoryCase
    found: list[str]

    @property
    def passed(self) -> bool:
        return self.found == sorted(self.case.expected)


SALES_ONLY = {"sales_total": Bounds(1, 2)}
SALES_OR_STOCK = {"sales_total": Bounds(1, 2), "stock_position": Bounds(0, 1)}

ANSWER = final("STATUS: answered\nForam 300 unidades.")

CASES: tuple[TrajectoryCase, ...] = (
    # --- trajetória limpa ---
    TrajectoryCase("one-call", (call_tool("sales_total"), ANSWER), SALES_ONLY, ()),
    TrajectoryCase(
        "retry-within-limit", (call_tool("sales_total"), call_tool("sales_total"), ANSWER), SALES_ONLY, ()
    ),
    # Dois caminhos igualmente certos: a ordem das tools opcionais não importa.
    TrajectoryCase(
        "optional-tool-first",
        (call_tool("stock_position"), call_tool("sales_total"), ANSWER),
        SALES_OR_STOCK,
        (),
    ),
    TrajectoryCase(
        "optional-tool-last",
        (call_tool("sales_total"), call_tool("stock_position"), ANSWER),
        SALES_OR_STOCK,
        (),
    ),
    # --- o que o código tem que pegar ---
    TrajectoryCase(
        "repeated-call-inflates-cost",
        (call_tool("sales_total"),) * 3 + (ANSWER,),
        SALES_ONLY,
        ("too_many:sales_total",),
    ),
    TrajectoryCase(
        "useless-tool",
        (call_tool("sales_total"), call_tool("stock_position"), ANSWER),
        SALES_ONLY,
        ("forbidden:stock_position",),
    ),
    TrajectoryCase("answer-without-tools", (ANSWER,), SALES_ONLY, ("missing:sales_total",)),
    TrajectoryCase(
        "optional-tool-too-many",
        (call_tool("sales_total"), call_tool("stock_position"), call_tool("stock_position"), ANSWER),
        SALES_OR_STOCK,
        ("too_many:stock_position",),
    ),
    TrajectoryCase(
        "never-converges",
        (call_tool("sales_total"),) * 3,
        {"sales_total": Bounds(1, 3)},
        ("over_budget",),
        max_steps=3,
    ),
    TrajectoryCase(
        "budget-blown-and-wasteful",
        (call_tool("sales_total"), call_tool("stock_position"), call_tool("stock_position")),
        SALES_ONLY,
        ("forbidden:stock_position", "over_budget"),
        max_steps=3,
    ),
)


def run_case(case: TrajectoryCase) -> TrajectoryResult:
    try:
        result = run_agent(
            ScriptedChat(*case.script),
            registry(),
            fake_ctx(),
            model="simulated",
            system="eval",
            user=QUESTION,
            max_steps=case.max_steps,
        )
        records: tuple[ToolCallRecord, ...] = result.tool_calls
        over = False
    except BudgetExceededError as exc:
        records, over = exc.tool_calls, True  # o orçamento estourado é violação, não crash do eval
    return TrajectoryResult(case, violations([r.name for r in records], case.limits, budget_exceeded=over))


def run(cases: tuple[TrajectoryCase, ...] = CASES) -> list[TrajectoryResult]:
    return [run_case(c) for c in cases]


def main() -> int:
    results = run()
    for r in results:
        if not r.passed:
            print(f"FAIL {r.case.name}: got {r.found}, expected {sorted(r.case.expected)}")
    passed = sum(r.passed for r in results)
    print(f"trajectory: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
