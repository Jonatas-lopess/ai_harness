"""Calibração do juiz: ele concorda com os rótulos humanos? E, mais importante, EM QUE erra?

Falso "fiel" (juiz aprova texto que um humano reprovou) é o erro perigoso: deixa passar o que o
código também não viu. Falso "infiel" só custa um retry ou uma revisão. Por isso a métrica que
decide é a taxa de falso "fiel", não a concordância total.

Aqui só há o cálculo. Os exemplos rotulados e o limite aceitável são do pack.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from harness.judge import Judge, Verdict
from harness.llm import ExtractionError, Usage, add_usage


@dataclass(frozen=True)
class LabeledExample:
    name: str
    facts: str
    text: str
    human: Verdict
    source: str  # de onde veio o rótulo (livre: o pack decide as categorias)


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
    max_false_faithful_rate: float  # calibrar de novo se o modelo do juiz mudar

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
        return self.false_faithful_rate <= self.max_false_faithful_rate


def calibrate(judge: Judge, data: Sequence[LabeledExample], *, max_false_faithful_rate: float) -> Report:
    """O limite é parâmetro obrigatório: quanto risco de falso "fiel" se aceita é decisão do pack."""
    outcomes: list[Outcome] = []
    for ex in data:
        try:
            r = judge.judge(ex.facts, ex.text)
            outcomes.append(Outcome(ex, r.verdict, r.reason, r.usage))
        except ExtractionError as exc:
            outcomes.append(Outcome(ex, None, f"judge failed: {exc}", exc.usage or Usage(0, 0)))
    return Report(tuple(outcomes), max_false_faithful_rate)


def summary(report: Report, *, model: str) -> str:
    lines = [
        f"model={model} examples={report.total} agreement={report.agreement:.0%} errors={report.errors}",
        f"false_faithful={report.false_faithful} rate={report.false_faithful_rate:.0%} "
        + f"(max {report.max_false_faithful_rate:.0%}) | "
        + f"false_unfaithful={report.false_unfaithful} rate={report.false_unfaithful_rate:.0%}",
        f"tokens prompt={report.usage.prompt_tokens} completion={report.usage.completion_tokens} "
        + "cost=n/d (no price registered)",
    ]
    return "\n".join(lines)
