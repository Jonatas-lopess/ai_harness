import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

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
    assert set(SUITES) == {"detection", "fidelity", "closing", "refusal", "trajectory"}


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


def test_history_entry_has_score_per_suite_and_cost() -> None:
    outcome: dict[str, list[Scored]] = {
        "a": [_Result(_Case("x"), True), _Result(_Case("y"), False)]
    }
    entry = runner.history_entry(outcome, commit="abc1234", day=date(2026, 10, 8))
    assert entry == {
        "date": "2026-10-08",
        "commit": "abc1234",
        "mode": "simulated",
        "scores": {"a": [1, 2]},
        "cost_usd": 0.0,
    }


def test_record_appends_one_json_line_per_run(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    outcome = run_all()
    runner.record(outcome, path)
    runner.record(outcome, path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert set(cast("dict[str, object]", json.loads(lines[0]))["scores"]) == set(SUITES)  # pyright: ignore[reportArgumentType]


def test_main_without_record_flag_does_not_write_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(runner, "HISTORY_PATH", path)
    _ = runner.main([])
    assert not path.exists()
