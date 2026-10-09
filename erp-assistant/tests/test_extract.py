import logging
from decimal import Decimal
from typing import Any

from pytest import LogCaptureFixture, raises

from erp_prices import load_erp_prices
from extract import ExtractionResult, StockMessage, extract_text, extract_with_retry, log_run_cost
from harness.llm import Completion, InvalidOutputError, ProviderUnavailableError, TruncatedOutputError, Usage

USAGE = Usage(prompt_tokens=10, completion_tokens=5)


class FakeClient:
    """Devolve uma resposta pronta e guarda os argumentos da chamada."""

    def __init__(self, completion: Completion) -> None:
        self.completion: Completion = completion
        self.calls: list[dict[str, Any]] = []  # pyright: ignore[reportExplicitAny]

    def complete(self, **kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.calls.append(kwargs)
        return self.completion


def make_result(prompt: int, completion: int, attempts: int = 1) -> ExtractionResult:
    return ExtractionResult(StockMessage(product_name="P", stock_level=1), Usage(prompt, completion), attempts)


def run(completion: Completion) -> StockMessage:
    return extract_text(FakeClient(completion), "texto qualquer", model="fake-model")


def test_valid_output() -> None:
    result = run(Completion('{"product_name": "Parafuso", "stock_level": 40}', "stop", usage=USAGE))

    assert result == StockMessage(product_name="Parafuso", stock_level=40)


def test_missing_field_stays_none() -> None:
    result = run(Completion('{"product_name": "Parafuso", "stock_level": null}', "stop"))

    assert result.stock_level is None


def test_sends_schema_and_params() -> None:
    client = FakeClient(Completion('{"product_name": null, "stock_level": null}', "stop"))

    _ = extract_text(client, "oi", model="fake-model", max_completion_tokens=99)

    call = client.calls[0]
    assert call["model"] == "fake-model"
    assert call["user"] == "oi"
    assert call["max_completion_tokens"] == 99
    assert call["response_schema"]["additionalProperties"] is False
    assert set(call["response_schema"]["required"]) == {"product_name", "stock_level"}  # pyright: ignore[reportAny]


class ScriptedClient:
    """Devolve uma resposta por chamada, na ordem; guarda os argumentos de cada chamada."""

    def __init__(self, *completions: Completion | Exception) -> None:
        self.completions: list[Completion | Exception] = list(completions)
        self.calls: list[dict[str, Any]] = []  # pyright: ignore[reportExplicitAny]

    def complete(self, **kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.calls.append(kwargs)
        item = self.completions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


BAD = Completion("isso não é json", "stop", usage=USAGE)
GOOD = Completion('{"product_name": "Parafuso", "stock_level": 40}', "stop", usage=USAGE)


def test_retry_succeeds_after_invalid_and_sums_usage() -> None:
    client = ScriptedClient(BAD, GOOD)

    result = extract_with_retry(client, "oi", model="m")

    assert result.value == StockMessage(product_name="Parafuso", stock_level=40)
    assert result.attempts == 2
    assert result.usage == Usage(20, 10)


def test_retry_feeds_error_back_in_prompt() -> None:
    client = ScriptedClient(BAD, GOOD)

    _ = extract_with_retry(client, "oi", model="m")

    assert client.calls[0]["user"] == "oi"
    assert client.calls[1]["user"].startswith("oi")  # pyright: ignore[reportAny]
    assert "rejeitada" in client.calls[1]["user"]


def test_retry_gives_up_after_max_attempts() -> None:
    client = ScriptedClient(BAD, BAD, BAD, GOOD)

    with raises(InvalidOutputError) as info:
        _ = extract_with_retry(client, "oi", model="m", max_attempts=3)

    assert len(client.calls) == 3
    assert info.value.usage == Usage(30, 15)


def test_retry_does_not_retry_truncated_and_keeps_usage() -> None:
    cut = Completion('{"product_name": "Para', "length", usage=USAGE)
    client = ScriptedClient(BAD, cut, GOOD)

    with raises(TruncatedOutputError) as info:
        _ = extract_with_retry(client, "oi", model="m")

    assert len(client.calls) == 2
    assert info.value.usage == Usage(20, 10)


def test_retry_rejects_zero_attempts() -> None:
    with raises(ValueError):
        _ = extract_with_retry(ScriptedClient(GOOD), "oi", model="m", max_attempts=0)


def test_retry_does_not_retry_provider_unavailable_and_keeps_usage() -> None:
    client = ScriptedClient(BAD, ProviderUnavailableError("down"), GOOD)

    with raises(ProviderUnavailableError) as info:
        _ = extract_with_retry(client, "oi", model="m")

    assert len(client.calls) == 2
    assert info.value.usage == Usage(10, 5)


def test_log_run_cost_known_model(caplog: LogCaptureFixture) -> None:
    table = load_erp_prices()

    with caplog.at_level(logging.INFO, logger="extract"):
        cost = log_run_cost(make_result(1000, 500, attempts=2), "openai/gpt-oss-120b", table)

    assert cost == Decimal("0.00045")
    assert "attempts=2" in caplog.text
    assert "cost=0.00045 USD" in caplog.text


def test_log_run_cost_unknown_model_warns(caplog: LogCaptureFixture) -> None:
    table = load_erp_prices()

    with caplog.at_level(logging.INFO, logger="extract"):
        cost = log_run_cost(make_result(10, 10), "modelo-sem-preco", table)

    assert cost is None
    assert "no price for model=modelo-sem-preco" in caplog.text
