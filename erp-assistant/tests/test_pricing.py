import logging
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError
from pytest import LogCaptureFixture, raises

from extract import ExtractionResult, StockMessage, Usage
from pricing import Price, compute_cost, load_prices, log_run_cost

PRICE = Price(input_per_mtok=Decimal("0.15"), output_per_mtok=Decimal("0.60"))


def make_result(prompt: int, completion: int, attempts: int = 1) -> ExtractionResult:
    return ExtractionResult(StockMessage(product_name="P", stock_level=1), Usage(prompt, completion), attempts)


def test_cost_is_exact() -> None:
    # 1M entrada * 0.15 + 1M saída * 0.60 = 0.75
    assert compute_cost(Usage(1_000_000, 1_000_000), PRICE) == Decimal("0.75")


def test_cost_small_usage_has_no_float_error() -> None:
    # 1000 * 0.15 / 1M = 0.00015 ; 500 * 0.60 / 1M = 0.0003
    assert compute_cost(Usage(1000, 500), PRICE) == Decimal("0.00045")


def test_cost_none_without_price() -> None:
    assert compute_cost(Usage(10, 10), None) is None


def test_load_default_prices_has_groq_model() -> None:
    table = load_prices()

    assert table.currency == "USD"
    assert Decimal("0.15") == table.models["openai/gpt-oss-120b"].input_per_mtok


def test_load_prices_rejects_unknown_field(tmp_path: Path) -> None:
    bad = tmp_path / "prices.json"
    _ = bad.write_text(
        '{"source": "s", "effective_date": "d", "currency": "USD", "models": {"m": {"input_per_mtok": "1", "output_per_mtok": "1", "extra": "x"}}}'
    )

    with raises(ValidationError):
        _ = load_prices(bad)


def test_log_run_cost_known_model(caplog: LogCaptureFixture) -> None:
    table = load_prices()

    with caplog.at_level(logging.INFO, logger="pricing"):
        cost = log_run_cost(make_result(1000, 500, attempts=2), "openai/gpt-oss-120b", table)

    assert cost == Decimal("0.00045")
    assert "attempts=2" in caplog.text
    assert "cost=0.00045 USD" in caplog.text


def test_log_run_cost_unknown_model_warns(caplog: LogCaptureFixture) -> None:
    table = load_prices()

    with caplog.at_level(logging.INFO, logger="pricing"):
        cost = log_run_cost(make_result(10, 10), "modelo-sem-preco", table)

    assert cost is None
    assert "no price for model=modelo-sem-preco" in caplog.text
