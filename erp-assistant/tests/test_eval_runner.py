import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from evals import __main__ as runner
from evals.__main__ import SUITES, run_all
from harness.evals import Scored


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


def test_main_without_record_flag_does_not_write_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(runner, "HISTORY_PATH", path)
    _ = runner.main([])
    assert not path.exists()


def test_record_flag_appends_one_line_to_the_erp_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(runner, "HISTORY_PATH", path)

    assert runner.main(["--record"]) == 0

    [line] = path.read_text().splitlines()
    assert set(cast("dict[str, object]", json.loads(line))["scores"]) == set(SUITES)  # pyright: ignore[reportArgumentType]
