from pytest import mark, raises

from extract import ExtractionError, InvalidOutputError, StockMessage, extract_text, extract_with_retry
from groq_client import GroqClient
from settings import get_settings

MODEL = "openai/gpt-oss-120b"


@mark.integration
def test_real_extraction() -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())

    result = extract_text(client, "Temos 40 parafusos M8 no estoque.", model=MODEL)

    assert isinstance(result, StockMessage)
    assert result.stock_level == 40


@mark.integration
def test_real_missing_data_stays_none() -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())

    result = extract_text(client, "Preciso saber como está o estoque.", model=MODEL)

    assert result.stock_level is None


@mark.integration
def test_real_truncation_raises_extraction_error() -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())

    with raises(ExtractionError):
        _ = extract_text(client, "Temos 40 parafusos M8 no estoque.", model=MODEL, max_completion_tokens=5)


@mark.integration
def test_real_retry_happy_path_reports_usage() -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())

    result = extract_with_retry(client, "Temos 40 parafusos M8 no estoque.", model=MODEL)

    assert result.value.stock_level == 40
    assert result.attempts == 1
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0


@mark.integration
def test_real_retry_exhausts_attempts_on_forced_failure() -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())

    # 5 tokens nunca cabem no JSON: o provedor devolve 400 em toda tentativa.
    with raises(InvalidOutputError, match="after 2 attempts"):
        _ = extract_with_retry(
            client, "Temos 40 parafusos M8 no estoque.", model=MODEL, max_completion_tokens=5, max_attempts=2
        )
