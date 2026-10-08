"""Calibração do juiz: ele concorda com os rótulos humanos? E, mais importante, EM QUE erra?

Falso "fiel" (juiz aprova texto que um humano reprovou) é o erro perigoso: deixa passar o que o
código também não viu. Falso "infiel" só custa um retry ou uma revisão. Por isso a métrica que
decide é a taxa de falso "fiel", não a concordância total.

Rótulos: `golden` herda dos golden sets de fidelidade e fechamento (aceito pelo código = fiel);
`gap` são casos que o código NÃO enxerga (lacunas documentadas no NOTES.md). Os `gap` foram
rotulados pela IA e esperam revisão do autor. Chamada real: `python -m evals.judge_calibration`.
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from closing import ClosingFacts
from evals import closing, fidelity
from extract import ExtractionError, Usage, add_usage
from judge import Judge, Verdict

MAX_FALSE_FAITHFUL_RATE = 0.10  # calibrar de novo se o modelo do juiz mudar

Source = Literal["golden", "gap"]

# Dia 10: o número 10 entra nos fatos (a data), então "10% acima" é grounded para o código.
DAY_10 = ClosingFacts(
    day=date(2026, 1, 10), revenue=Decimal("10950.00"), units=465, top_product="received-po"
)


@dataclass(frozen=True)
class LabeledExample:
    name: str
    facts: str
    text: str
    human: Verdict
    source: Source


def _verdict(accepted: bool) -> Verdict:
    return "faithful" if accepted else "unfaithful"


def _gap(name: str, facts: str, text: str, human: Verdict) -> LabeledExample:
    return LabeledExample(name, facts, text, human, "gap")


_CLOSING = closing.FACTS.model_dump_json()
_DAY_10 = DAY_10.model_dump_json()
_REFILL = fidelity.F1.model_dump_json()

GAP_EXAMPLES: tuple[LabeledExample, ...] = (
    # --- lacunas do código: afirmação sem número, causa, comparação, atribuição ---
    _gap("forecast-no-number", _CLOSING, "Faturamento de R$ 10.950,00 e 465 unidades; deve crescer no próximo mês.", "unfaithful"),
    _gap("best-day-claim", _CLOSING, "Faturamento de R$ 10.950,00, o melhor dia do mês.", "unfaithful"),
    _gap("invented-cause", _CLOSING, "Faturamento de R$ 10.950,00 impulsionado por uma promoção.", "unfaithful"),
    _gap("invented-trend", _CLOSING, "Forte alta nas vendas, com 465 unidades.", "unfaithful"),
    _gap("invented-recommendation", _CLOSING, "Faturamento de R$ 10.950,00; recomendo aumentar o estoque de received-po.", "unfaithful"),
    _gap("misattributed-units", _CLOSING, "O produto received-po vendeu 465 unidades.", "unfaithful"),
    _gap("percent-equals-date-part", _DAY_10, "Faturamento de R$ 10.950,00, 10% acima do dia anterior.", "unfaithful"),
    _gap("refill-invented-cause", _REFILL, "Estoque 3 abaixo do ponto 40; repor 250 antes que o fornecedor aumente o preço.", "unfaithful"),
    _gap("refill-forecast-no-number", _REFILL, "Estoque 3 abaixo do ponto 40; a ruptura deve ocorrer amanhã.", "unfaithful"),
    # --- fiéis que o juiz não pode reprovar ---
    _gap("faithful-date", _CLOSING, "Fechamento de 20/01/2026: R$ 10.950,00 em vendas.", "faithful"),
    _gap("faithful-top-product", _CLOSING, "O produto de maior faturamento do dia foi received-po.", "faithful"),
    _gap("faithful-date-part-as-date", _DAY_10, "Em 10/01/2026 o faturamento foi de R$ 10.950,00.", "faithful"),
    _gap("faithful-refill-no-numbers", _REFILL, "Estoque abaixo do ponto de reposição; reposição sugerida.", "faithful"),
)


def examples() -> tuple[LabeledExample, ...]:
    golden = tuple(
        LabeledExample(f"fidelity/{c.name}", c.facts.model_dump_json(), c.text, _verdict(c.expected_accepted), "golden")
        for c in fidelity.CASES
    ) + tuple(
        LabeledExample(f"closing/{c.name}", _CLOSING, c.text, _verdict(c.expected_accepted), "golden")
        for c in closing.CASES
    )
    return golden + GAP_EXAMPLES


@dataclass(frozen=True)
class Outcome:
    example: LabeledExample
    judged: Verdict | None  # None = o juiz falhou (saída inválida, provedor fora)
    reason: str
    usage: Usage

    @property
    def agrees(self) -> bool:
        return self.judged == self.example.human


@dataclass(frozen=True)
class Report:
    outcomes: tuple[Outcome, ...]

    def _count(self, human: Verdict, judged: Verdict | None) -> int:
        return sum(o.example.human == human and o.judged == judged for o in self.outcomes)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def agreement(self) -> float:
        return sum(o.agrees for o in self.outcomes) / self.total

    @property
    def false_faithful(self) -> int:
        """Humano reprovou, juiz aprovou: o erro perigoso."""
        return self._count("unfaithful", "faithful")

    @property
    def false_unfaithful(self) -> int:
        return self._count("faithful", "unfaithful")

    @property
    def errors(self) -> int:
        return sum(o.judged is None for o in self.outcomes)

    @property
    def false_faithful_rate(self) -> float:
        """Falhas de juiz contam como erro perigoso: sem veredito não houve proteção."""
        unfaithful = [o for o in self.outcomes if o.example.human == "unfaithful"]
        missed = sum(o.judged != "unfaithful" for o in unfaithful)
        return missed / len(unfaithful)

    @property
    def false_unfaithful_rate(self) -> float:
        faithful = [o for o in self.outcomes if o.example.human == "faithful"]
        return sum(o.judged != "faithful" for o in faithful) / len(faithful)

    @property
    def usage(self) -> Usage:
        total = Usage(0, 0)
        for o in self.outcomes:
            total = add_usage(total, o.usage)
        return total

    @property
    def trustworthy(self) -> bool:
        return self.false_faithful_rate <= MAX_FALSE_FAITHFUL_RATE


def calibrate(judge: Judge, data: Sequence[LabeledExample] | None = None) -> Report:
    outcomes: list[Outcome] = []
    for ex in data if data is not None else examples():
        try:
            r = judge.judge(ex.facts, ex.text)
            outcomes.append(Outcome(ex, r.verdict, r.reason, r.usage))
        except ExtractionError as exc:
            outcomes.append(Outcome(ex, None, f"judge failed: {exc}", exc.usage or Usage(0, 0)))
    return Report(tuple(outcomes))


def main() -> int:
    from groq_client import GroqClient
    from judge import LLMJudge
    from settings import get_settings

    model = "qwen/qwen3.8-27b"
    settings = get_settings()
    client = GroqClient(
        settings.groq_api_key.get_secret_value(),
        max_retries=settings.groq_max_retries,
        timeout=settings.groq_timeout_seconds,
    )
    report = calibrate(LLMJudge(client, model))
    for o in report.outcomes:
        if not o.agrees:
            print(f"DISAGREE {o.example.name} [{o.example.source}] human={o.example.human} judge={o.judged}: {o.reason}")
    print(f"model={model} examples={report.total} agreement={report.agreement:.0%} errors={report.errors}")
    print(
        f"false_faithful={report.false_faithful} rate={report.false_faithful_rate:.0%} (max {MAX_FALSE_FAITHFUL_RATE:.0%}) | "
        + f"false_unfaithful={report.false_unfaithful} rate={report.false_unfaithful_rate:.0%}"
    )
    print(
        f"tokens prompt={report.usage.prompt_tokens} completion={report.usage.completion_tokens} "
        + "cost=n/d (no price registered)"
    )
    return 0 if report.trustworthy else 1


if __name__ == "__main__":
    sys.exit(main())
