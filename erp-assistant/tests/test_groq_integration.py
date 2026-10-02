from pytest import mark, raises

from extract import ExtractionError, StockMessage, extract_text
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
