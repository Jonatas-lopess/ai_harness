"""Calibração do juiz: ele concorda com os rótulos humanos? E, mais importante, EM QUE erra?

Falso "fiel" (juiz aprova texto que um humano reprovou) é o erro perigoso: deixa passar o que o
código também não viu. Falso "infiel" só custa um retry ou uma revisão. Por isso a métrica que
decide é a taxa de falso "fiel", não a concordância total.

O cálculo (concordância, falso "fiel") é de `harness.calibration`; aqui ficam os exemplos rotulados e o limite.

Rótulos: `golden` herda dos golden sets de fidelidade e fechamento (aceito pelo código = fiel);
`gap` são casos que o código NÃO enxerga (lacunas documentadas no NOTES.md). Os `gap` foram
rotulados pela IA e esperam revisão do autor. Chamada real: `python -m evals.judge_calibration`.
"""

import sys
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from closing import ClosingFacts
from evals import closing, fidelity
from harness.calibration import LabeledExample, Report, summary
from harness.calibration import calibrate as _calibrate
from harness.judge import Judge, Verdict

MAX_FALSE_FAITHFUL_RATE = 0.10  # calibrar de novo se o modelo do juiz mudar

# Dia 10: o número 10 entra nos fatos (a data), então "10% acima" é grounded para o código.
DAY_10 = ClosingFacts(
    day=date(2026, 1, 10), revenue=Decimal("10950.00"), units=465, top_product="received-po"
)


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


def calibrate(judge: Judge, data: Sequence[LabeledExample] | None = None) -> Report:
    return _calibrate(
        judge, data if data is not None else examples(), max_false_faithful_rate=MAX_FALSE_FAITHFUL_RATE
    )


def main() -> int:
    from harness.providers.groq import GroqClient
    from harness.judge import LLMJudge
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
    print(summary(report, model=model))
    return 0 if report.trustworthy else 1


if __name__ == "__main__":
    sys.exit(main())
