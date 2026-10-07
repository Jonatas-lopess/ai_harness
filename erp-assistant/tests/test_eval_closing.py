from dataclasses import replace
from datetime import date
from decimal import Decimal

from closing import ClosingFacts
from closing_job import FIELD_ALIASES, narrate_closing
from evals.clients import FixedClient
from evals.closing import CASES, FACTS, run, run_case
from validators import mislabeled_numbers


def test_closing_golden_set_passes() -> None:
    assert [r.case.name for r in run() if not r.passed] == []


def test_closing_golden_set_has_both_verdicts() -> None:
    assert {c.expected_accepted for c in CASES} == {True, False}
    assert len(CASES) >= 15


def test_wrong_expectation_fails_the_case() -> None:
    wrong_total = next(c for c in CASES if c.name == "wrong-total")
    assert not run_case(replace(wrong_total, expected_accepted=True)).passed


def test_label_belongs_to_the_neighbouring_number_only() -> None:
    # `R$` é do 10.950,00; o 465 não pode herdá-lo só por ser o rótulo anterior mais próximo.
    values = FACTS.labelled_values()
    text = "Faturamento de R$ 10.950,00 com 465 unidades"
    assert mislabeled_numbers(text, values, FIELD_ALIASES) == []


def test_known_gap_percent_equal_to_a_date_part_is_grounded() -> None:
    # Limite assumido: o dia 10 está nos fatos (data), então "10%" inventado tem "origem".
    facts = ClosingFacts(
        day=date(2026, 1, 10), revenue=Decimal("10950.00"), units=465, top_product="x"
    )
    text = "Faturamento de R$ 10.950,00, 10% acima do dia anterior."

    assert narrate_closing(FixedClient(text), facts, model="m", max_attempts=1).rationale == text


def test_known_gap_forecast_without_numbers_is_accepted() -> None:
    # Limite assumido: validador de número não vê projeção sem número. Passo 4 (recusa).
    text = "O faturamento de R$ 10.950,00 deve crescer no próximo mês."

    assert narrate_closing(FixedClient(text), FACTS, model="m", max_attempts=1).rationale == text
