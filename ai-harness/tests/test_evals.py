import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pytest import CaptureFixture

from harness.evals import Scored, history_entry, main, record, run_all


@dataclass(frozen=True)
class _Case:
    name: str


@dataclass(frozen=True)
class _Result:
    case: _Case
    passed: bool


def _green() -> list[Scored]:
    return [_Result(_Case("a"), True), _Result(_Case("b"), True)]


def _red() -> list[Scored]:
    return [_Result(_Case("ok"), True), _Result(_Case("wrong-number"), False)]


def test_run_all_runs_exactly_the_suites_the_pack_registered() -> None:
    assert list(run_all({"one": _green, "two": _red})) == ["one", "two"]


def test_main_exits_zero_when_every_case_passes(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    assert main([], suites={"one": _green}, history_path=tmp_path / "h.jsonl") == 0

    assert "one: 2/2" in capsys.readouterr().out


def test_main_exits_one_and_names_the_failing_case(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    code = main([], suites={"one": _green, "two": _red}, history_path=tmp_path / "h.jsonl")

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL two/wrong-number" in out and "total: 3/4" in out


def test_history_entry_has_score_per_suite_and_cost() -> None:
    entry = history_entry({"a": _red()}, commit="abc1234", day=date(2026, 10, 8))

    assert entry == {
        "date": "2026-10-08",
        "commit": "abc1234",
        "mode": "simulated",
        "scores": {"a": [1, 2]},
        "cost_usd": 0.0,
    }


def test_record_appends_one_json_line_per_run(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    outcome = run_all({"a": _green})

    record(outcome, path)
    record(outcome, path)

    lines = path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["scores"] == {"a": [2, 2]}


def test_history_is_written_only_with_the_record_flag(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"

    _ = main([], suites={"a": _green}, history_path=path)
    assert not path.exists()

    _ = main(["--record"], suites={"a": _green}, history_path=path)
    assert path.exists()
