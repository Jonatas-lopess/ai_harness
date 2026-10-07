from dataclasses import replace

from evals.fidelity import CASES, F1, run, run_case
from validators import mislabeled_numbers

VALUES = F1.labelled_values()
ALIASES = {
    "on_hand": ("estoque",),
    "reorder_point": ("ponto",),
    "suggested_qty": ("repor",),
}


def test_fidelity_golden_set_passes() -> None:
    failures = [r.case.name for r in run() if not r.passed]
    assert failures == []


def test_fidelity_golden_set_has_both_verdicts() -> None:
    assert {c.expected_accepted for c in CASES} == {True, False}
    assert len(CASES) >= 15


def test_wrong_expectation_fails_the_case() -> None:
    swapped = next(c for c in CASES if c.name == "swap-on-hand-and-point")
    assert not run_case(replace(swapped, expected_accepted=True)).passed


def test_mislabeled_reports_the_field() -> None:
    wrong = mislabeled_numbers("O estoque é 40.", VALUES, ALIASES)
    assert wrong == ["40 (next to 'on_hand', which is 3)"]


def test_clause_split_keeps_thousands_separator_together() -> None:
    values = {"on_hand": 1250, "reorder_point": 9}
    assert mislabeled_numbers("Estoque 1.250.", values, ALIASES) == []


def test_known_gap_number_without_label_in_its_clause_is_not_judged() -> None:
    # Limite assumido: "40 itens" sem rótulo na oração passa mesmo sendo o ponto de reposição.
    assert mislabeled_numbers("Há 40 itens, abaixo do ponto.", VALUES, ALIASES) == []
