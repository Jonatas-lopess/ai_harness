from pytest import mark

from evals.judge_calibration import GAP_EXAMPLES, LabeledExample
from groq_client import GroqClient
from judge import LLMJudge
from settings import get_settings

MODEL = "qwen/qwen3.8-27b"  # família diferente da do gerador (gpt-oss): reduz viés de autopreferência


def make_judge() -> LLMJudge:
    settings = get_settings()
    client = GroqClient(
        settings.groq_api_key.get_secret_value(),
        max_retries=settings.groq_max_retries,
        timeout=settings.groq_timeout_seconds,
    )
    return LLMJudge(client, MODEL)


def _example(name: str) -> LabeledExample:
    return next(e for e in GAP_EXAMPLES if e.name == name)


@mark.integration
def test_real_judge_rejects_a_forecast_with_no_numbers() -> None:
    e = _example("forecast-no-number")
    assert make_judge().judge(e.facts, e.text).verdict == "unfaithful"


@mark.integration
def test_real_judge_accepts_a_faithful_summary() -> None:
    e = _example("faithful-top-product")
    assert make_judge().judge(e.facts, e.text).verdict == "faithful"
