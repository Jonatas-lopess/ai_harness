from dataclasses import replace

from evals.detection import CASES, Case, run, run_case, score_by_group


def test_golden_set_has_enough_cases_in_both_groups() -> None:
    groups = {c.group for c in CASES}
    assert groups == {"detection", "false_alarm"}
    assert len(CASES) >= 20


def test_case_names_are_unique() -> None:
    assert len({c.name for c in CASES}) == len(CASES)


def test_golden_set_passes() -> None:
    # É este teste que falha no CI quando a regra de reposição muda um número.
    failures = [r for r in run() if not r.passed]
    assert failures == []


def test_wrong_quantity_fails_the_case() -> None:
    wrong = replace(CASES[0], expected_qty=CASES[0].expected_qty + 1)
    assert not run_case(wrong).passed


def test_missed_flag_fails_the_case() -> None:
    # Esperar "não sinaliza" num caso que sinaliza tem que reprovar.
    wrong: Case = replace(CASES[0], expected_flagged=False, expected_qty=0)
    assert not run_case(wrong).passed


def test_score_by_group_counts_failures() -> None:
    wrong = replace(CASES[0], expected_qty=0)
    scores = score_by_group(run((wrong, CASES[1])))
    assert scores == {"detection": (1, 2)}
