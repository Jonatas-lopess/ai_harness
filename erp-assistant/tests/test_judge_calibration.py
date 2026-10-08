from closing import ClosingFacts
from closing_job import narrate_closing
from evals.clients import FixedClient
from refill_job import RefillFacts, explain
from extract import ProviderUnavailableError, Usage
from evals.judge_calibration import GAP_EXAMPLES, examples, calibrate
from judge import JudgeResult, Verdict


class _Constant:
    def __init__(self, verdict: Verdict) -> None:
        self._verdict: Verdict = verdict

    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts, text
        return JudgeResult(self._verdict, "", Usage(1, 1))


class _Oracle:
    """Concorda com o rótulo humano: o juiz perfeito."""

    def __init__(self) -> None:
        self._by_text: dict[str, Verdict] = {e.text: e.human for e in examples()}

    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts
        return JudgeResult(self._by_text[text], "", Usage(1, 1))


class _Down:
    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts, text
        raise ProviderUnavailableError("down", Usage(3, 0))


def test_examples_have_unique_names_and_both_labels() -> None:
    data = examples()
    assert len({e.name for e in data}) == len(data)
    assert {e.human for e in data} == {"faithful", "unfaithful"}
    assert {e.source for e in data} == {"golden", "gap"}


def test_every_example_text_is_unique_for_the_oracle() -> None:
    # `_Oracle` indexa por texto: texto repetido com rótulos diferentes quebraria o teste.
    data = examples()
    assert len({(e.text, e.facts) for e in data}) == len(data)


def test_unfaithful_gap_examples_really_slip_past_the_code() -> None:
    # Se o caminho de produção já rejeita o texto, o caso não é lacuna e não prova o valor do juiz.
    for e in GAP_EXAMPLES:
        if e.human != "unfaithful":
            continue
        if "product_id" in e.facts:
            refill = explain(FixedClient(e.text), RefillFacts.model_validate_json(e.facts), model="m", max_attempts=1)
            accepted = refill.rationale == e.text
        else:
            closing = narrate_closing(FixedClient(e.text), ClosingFacts.model_validate_json(e.facts), model="m", max_attempts=1)
            accepted = closing.rationale == e.text
        assert accepted, e.name


def test_perfect_judge_agrees_everywhere() -> None:
    report = calibrate(_Oracle())
    assert report.agreement == 1.0
    assert report.false_faithful == report.false_unfaithful == 0
    assert report.trustworthy


def test_judge_that_approves_everything_is_not_trustworthy() -> None:
    report = calibrate(_Constant("faithful"))
    assert report.false_faithful_rate == 1.0
    assert report.false_unfaithful_rate == 0.0
    assert not report.trustworthy


def test_judge_that_rejects_everything_is_safe_but_useless() -> None:
    report = calibrate(_Constant("unfaithful"))
    assert report.false_faithful_rate == 0.0
    assert report.false_unfaithful_rate == 1.0
    assert report.trustworthy  # a métrica de segurança sozinha não basta: olhe os dois números


def test_judge_failure_counts_as_a_miss_and_keeps_usage() -> None:
    report = calibrate(_Down())
    assert report.errors == report.total
    assert report.false_faithful_rate == 1.0  # sem veredito não houve proteção
    assert report.usage == Usage(3 * report.total, 0)


def test_usage_sums_over_examples() -> None:
    report = calibrate(_Constant("faithful"))
    assert report.usage == Usage(report.total, report.total)
