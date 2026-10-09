from closing import ClosingFacts
from closing_job import narrate_closing
from harness.testing import FixedClient
from refill_job import RefillFacts, explain
from harness.llm import Usage
from evals.judge_calibration import GAP_EXAMPLES, examples, calibrate
from harness.judge import JudgeResult, Verdict


class _Oracle:
    """Concorda com o rótulo humano: o juiz perfeito."""

    def __init__(self) -> None:
        self._by_text: dict[str, Verdict] = {e.text: e.human for e in examples()}

    def judge(self, facts: str, text: str) -> JudgeResult:
        del facts
        return JudgeResult(self._by_text[text], "", Usage(1, 1))


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
