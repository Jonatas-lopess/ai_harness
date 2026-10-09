import logging
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError
from pytest import LogCaptureFixture, raises

from harness.llm import Usage
from extract import ExtractionResult, StockMessage
from pricing import JobCost, Price, PriceTable, compute_cost, costed_span, job_cost, load_prices, log_run_cost, usage_attributes
from harness.tracing import MemorySink, Span, span, trace

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


TABLE = PriceTable(
    source="test", effective_date="2026-01-01", currency="USD", models={"known": PRICE}
)


def llm_span(model: str, usage: Usage | None, table: PriceTable = TABLE) -> None:
    with span("llm_call", model=model) as s:
        s.set(**usage_attributes(usage, model, table))


def test_usage_attributes_freeze_cost_and_price_date() -> None:
    attrs = usage_attributes(Usage(1000, 500), "known", TABLE)

    assert attrs == {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "cost": Decimal("0.00045"),
        "currency": "USD",
        "prices_as_of": "2026-01-01",
    }


def test_usage_attributes_unknown_model_and_missing_usage_have_no_cost() -> None:
    assert usage_attributes(Usage(10, 5), "other", TABLE)["cost"] is None
    missing = usage_attributes(None, "known", TABLE)
    assert missing["cost"] is None and missing["prompt_tokens"] is None


def test_job_cost_sums_known_calls_and_flags_the_partial_total() -> None:
    sink = MemorySink()
    with trace("t", sink):
        llm_span("known", Usage(1000, 500))
        llm_span("known", Usage(1000, 500))
        llm_span("other", Usage(2000, 100))  # sem preço: entra nos tokens, não no custo
    spans = sink.traces[0].spans

    assert job_cost(spans) == JobCost(
        cost=Decimal("0.0009"),
        complete=False,
        calls=3,
        calls_without_cost=1,
        prompt_tokens=4000,
        completion_tokens=1100,
    )


def test_job_cost_complete_when_every_call_has_a_price() -> None:
    sink = MemorySink()
    with trace("t", sink):
        llm_span("known", Usage(1000, 500))
    assert job_cost(sink.traces[0].spans).complete is True


def test_job_cost_ignores_spans_that_are_not_llm_calls() -> None:
    other = Span("t", "s", None, "tool", "now", attributes={"cost": Decimal("9")})
    assert job_cost([other]) == JobCost(Decimal(0), True, 0, 0, 0, 0)


def test_costed_span_records_cost_per_job_inside_a_shared_trace() -> None:
    sink = MemorySink()
    with trace("t", sink):
        with costed_span("job_a", prompt_version="a-v1"):
            llm_span("known", Usage(1000, 500))
        with costed_span("job_b"):
            llm_span("known", Usage(2000, 1000))
    _, a, _, b, _ = sink.traces[0].spans

    assert a.attributes["cost"] == Decimal("0.00045")
    assert a.attributes["prompt_version"] == "a-v1"
    assert b.attributes["cost"] == Decimal("0.0009")  # não soma o job_a
    assert a.attributes["cost_complete"] is True


def test_costed_span_records_the_spend_even_when_the_job_fails() -> None:
    sink = MemorySink()
    with raises(RuntimeError, match="boom"):
        with trace("t", sink):
            with costed_span("job"):
                llm_span("known", Usage(1000, 500))
                raise RuntimeError("boom")
    job = sink.traces[0].spans[1]

    assert job.status == "error"
    assert job.attributes["cost"] == Decimal("0.00045")  # falha também gasta


def test_costed_span_without_a_trace_runs_and_records_nothing() -> None:
    with costed_span("job") as job:
        llm_span("known", Usage(1000, 500))
    assert job.attributes["llm_calls"] == 0
