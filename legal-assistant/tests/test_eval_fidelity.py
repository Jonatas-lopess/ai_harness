from dataclasses import replace

from harness.testing import FixedClient

from evals.fidelity import CASES, OVERDUE, UPCOMING, FidelityCase, run, run_case
from legal_digest import build_digest
from legal_tools import UpcomingDeadlinesOutput


def test_fidelity_golden_set_passes() -> None:
    assert [r.case.name for r in run() if not r.passed] == []


def test_fidelity_golden_set_has_both_verdicts_and_both_rows() -> None:
    assert {c.expected_accepted for c in CASES} == {True, False}
    assert {c.row for c in CASES} == {"upcoming", "overdue"}
    assert len(CASES) >= 15


def test_wrong_expectation_fails_the_case() -> None:
    wrong_day = next(c for c in CASES if c.name == "wrong-day")
    assert not run_case(replace(wrong_day, expected_accepted=True)).passed


def test_the_dates_of_the_cases_are_the_ones_in_the_rows() -> None:
    # Os textos dos casos são escritos à mão: se a linha mudar, os casos "fiéis" têm que mudar junto.
    assert (UPCOMING.due_date, OVERDUE.due_date) == ("2026-03-13", "2026-03-02")


# --- lacunas conhecidas: o validador não lê o resto das palavras. Documentadas, não escondidas. ------------------------


def _sentence(text: str) -> str | None:
    output = UpcomingDeadlinesOutput(overdue=[], upcoming=[UPCOMING])
    return build_digest(FixedClient(text), output, model="m", max_attempts=1).items[0].sentence


def test_known_gap_advice_without_numbers_is_accepted() -> None:
    text = "O prazo de contestação vence em 13/03/2026. Recomendo pedir dilação do prazo."

    assert _sentence(text) == text


def test_known_gap_a_sentence_that_omits_the_date_is_accepted() -> None:
    # Completude não é validada: a frase só não pode afirmar o que o registro não tem.
    text = "Há uma contestação pendente neste processo."

    assert _sentence(text) == text


def test_case_dataclass_defaults_to_the_upcoming_row() -> None:
    assert FidelityCase("x", "y", True).row == "upcoming"
