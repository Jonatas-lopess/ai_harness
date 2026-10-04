import asyncio

from pytest import mark, raises

from extract import (
    ExtractionError,
    ExtractionResult,
    InvalidOutputError,
    StockMessage,
    extract_many,
    extract_text,
    extract_with_retry,
)
from groq_client import AsyncGroqClient, GroqClient
from pricing import load_prices, log_run_cost
from settings import get_settings

MODEL = "openai/gpt-oss-120b"


def make_client() -> GroqClient:
    settings = get_settings()
    return GroqClient(
        settings.groq_api_key.get_secret_value(),
        max_retries=settings.groq_max_retries,
        timeout=settings.groq_timeout_seconds,
    )


@mark.integration
def test_real_extraction() -> None:
    client = make_client()

    result = extract_text(client, "Temos 40 parafusos M8 no estoque.", model=MODEL)

    assert isinstance(result, StockMessage)
    assert result.stock_level == 40


@mark.integration
def test_real_missing_data_stays_none() -> None:
    client = make_client()

    result = extract_text(client, "Preciso saber como está o estoque.", model=MODEL)

    assert result.stock_level is None


@mark.integration
def test_real_truncation_raises_extraction_error() -> None:
    client = make_client()

    with raises(ExtractionError):
        _ = extract_text(client, "Temos 40 parafusos M8 no estoque.", model=MODEL, max_completion_tokens=5)


@mark.integration
def test_real_retry_happy_path_reports_usage() -> None:
    client = make_client()

    result = extract_with_retry(client, "Temos 40 parafusos M8 no estoque.", model=MODEL)

    assert result.value.stock_level == 40
    assert result.attempts == 1
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0


@mark.integration
def test_real_retry_exhausts_attempts_on_forced_failure() -> None:
    client = make_client()

    # 5 tokens nunca cabem no JSON: o provedor devolve 400 em toda tentativa.
    with raises(InvalidOutputError, match="after 2 attempts"):
        _ = extract_with_retry(
            client, "Temos 40 parafusos M8 no estoque.", model=MODEL, max_completion_tokens=5, max_attempts=2
        )


@mark.integration
def test_real_run_cost_is_positive_and_matches_usage() -> None:
    client = make_client()
    table = load_prices()

    result = extract_with_retry(client, "Temos 40 parafusos M8 no estoque.", model=MODEL)
    cost = log_run_cost(result, MODEL, table)

    price = table.models[MODEL]
    expected = (
        result.usage.prompt_tokens * price.input_per_mtok
        + result.usage.completion_tokens * price.output_per_mtok
    ) / 1_000_000
    assert cost is not None and cost > 0
    assert cost == expected


@mark.integration
def test_real_extract_many_async() -> None:
    settings = get_settings()
    client = AsyncGroqClient(
        settings.groq_api_key.get_secret_value(),
        max_retries=settings.groq_max_retries,
        timeout=settings.groq_timeout_seconds,
    )
    texts = ["Temos 40 parafusos M8 no estoque.", "Sobraram 7 porcas.", "Quanto temos de arruelas?"]

    results = asyncio.run(extract_many(client, texts, model=MODEL, max_concurrency=2))

    assert [r.value.stock_level for r in results if isinstance(r, ExtractionResult)] == [40, 7, None]
