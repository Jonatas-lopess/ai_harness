from harness.calibration import LabeledExample, calibrate, summary
from harness.judge import JudgeResult, Verdict
from harness.llm import ProviderUnavailableError, Usage

DATA = (
    LabeledExample("ok-1", "{}", "texto fiel 1", "faithful", "x"),
    LabeledExample("ok-2", "{}", "texto fiel 2", "faithful", "x"),
    LabeledExample("bad-1", "{}", "texto infiel 1", "unfaithful", "y"),
    LabeledExample("bad-2", "{}", "texto infiel 2", "unfaithful", "y"),
)


class _Constant:
    def __init__(self, verdict: Verdict) -> None:
        self._verdict: Verdict = verdict

    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts, text
        return JudgeResult(self._verdict, "", Usage(1, 1))


class _Oracle:
    """Concorda com o rótulo humano: o juiz perfeito."""

    def __init__(self) -> None:
        self._by_text: dict[str, Verdict] = {e.text: e.human for e in DATA}

    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts
        return JudgeResult(self._by_text[text], "", Usage(1, 1))


class _Down:
    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts, text
        raise ProviderUnavailableError("down", Usage(3, 0))


def _run(judge: _Constant | _Oracle | _Down, limit: float = 0.10):
    return calibrate(judge, DATA, max_false_faithful_rate=limit)


def test_perfect_judge_agrees_everywhere() -> None:
    report = _run(_Oracle())

    assert report.agreement == 1.0
    assert report.false_faithful == report.false_unfaithful == 0
    assert report.trustworthy


def test_judge_that_approves_everything_is_not_trustworthy() -> None:
    report = _run(_Constant("faithful"))

    assert report.false_faithful_rate == 1.0 and report.false_unfaithful_rate == 0.0
    assert not report.trustworthy


def test_judge_that_rejects_everything_is_safe_but_useless() -> None:
    report = _run(_Constant("unfaithful"))

    assert report.false_faithful_rate == 0.0 and report.false_unfaithful_rate == 1.0
    assert report.trustworthy  # a métrica de segurança sozinha não basta: olhe os dois números


def test_judge_failure_counts_as_a_miss_and_keeps_usage() -> None:
    report = _run(_Down())

    assert report.errors == report.total
    assert report.false_faithful_rate == 1.0  # sem veredito não houve proteção
    assert report.usage == Usage(3 * report.total, 0)


def test_usage_sums_over_examples() -> None:
    report = _run(_Constant("faithful"))

    assert report.usage == Usage(report.total, report.total)


def test_the_limit_is_the_packs_decision_and_the_boundary_is_inclusive() -> None:
    half = _Constant("faithful")  # aprova os 2 infiéis: taxa de falso fiel = 100%

    assert not _run(half, limit=0.99).trustworthy
    assert _run(half, limit=1.0).trustworthy


def test_summary_names_the_model_and_the_limit() -> None:
    text = summary(_run(_Oracle(), limit=0.25), model="m-x")

    assert "model=m-x examples=4 agreement=100%" in text
    assert "(max 25%)" in text
