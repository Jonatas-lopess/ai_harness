from dataclasses import dataclass

import pytest
from evals import __main__ as runner
from evals.__main__ import SUITES, Scored, run_all


@dataclass(frozen=True)
class _Case:
    name: str


@dataclass(frozen=True)
class _Result:
    case: _Case
    passed: bool


def test_runner_covers_every_golden_set() -> None:
    assert set(SUITES) == {"detection", "fidelity", "closing", "refusal"}


def test_all_golden_sets_pass_together() -> None:
    outcome = run_all()
    assert [(n, r.case.name) for n, rs in outcome.items() for r in rs if not r.passed] == []
    assert all(len(rs) > 0 for rs in outcome.values())


def test_main_exits_zero_when_all_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert runner.main() == 0
    assert "total:" in capsys.readouterr().out


def test_main_exits_one_and_names_the_failing_case(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> list[Scored]:
        return [_Result(_Case("ok"), True), _Result(_Case("wrong-number"), False)]

    monkeypatch.setitem(runner.SUITES, "fidelity", broken)
    assert runner.main() == 1
    assert "FAIL fidelity/wrong-number" in capsys.readouterr().out
