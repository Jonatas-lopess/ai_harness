from dataclasses import replace

from evals.trajectory import CASES, Bounds, run, run_case, violations


def test_trajectory_golden_set_passes() -> None:
    assert [r.case.name for r in run() if not r.passed] == []


def test_golden_set_has_clean_and_violating_cases_of_every_kind() -> None:
    kinds = {v.split(":")[0] for c in CASES for v in c.expected}
    assert kinds == {"forbidden", "missing", "too_many", "over_budget"}
    assert any(not c.expected for c in CASES)


def test_order_does_not_matter() -> None:
    limits = {"a": Bounds(1, 1), "b": Bounds(1, 1)}
    assert violations(["a", "b"], limits) == violations(["b", "a"], limits) == []


def test_unlisted_tool_is_forbidden() -> None:
    assert violations(["a", "x"], {"a": Bounds(1, 1)}) == ["forbidden:x"]


def test_count_outside_bounds_is_a_violation() -> None:
    limits = {"a": Bounds(1, 2)}
    assert violations([], limits) == ["missing:a"]
    assert violations(["a"] * 3, limits) == ["too_many:a"]


def test_wrong_expectation_fails_the_case() -> None:
    clean = next(c for c in CASES if not c.expected)
    assert not run_case(replace(clean, expected=("too_many:sales_total",))).passed


def test_budget_exceeded_is_a_violation_not_a_crash() -> None:
    blown = next(c for c in CASES if c.name == "never-converges")
    assert run_case(blown).found == ["over_budget"]
