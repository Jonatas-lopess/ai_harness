from typing import Any

from pytest import raises

from extract import (
    Completion,
    ExtractionError,
    InvalidOutputError,
    RefusedError,
    StockMessage,
    TruncatedOutputError,
    Usage,
    extract_text,
)

USAGE = Usage(prompt_tokens=10, completion_tokens=5)


class FakeClient:
    """Devolve uma resposta pronta e guarda os argumentos da chamada."""

    def __init__(self, completion: Completion) -> None:
        self.completion: Completion = completion
        self.calls: list[dict[str, Any]] = []  # pyright: ignore[reportExplicitAny]

    def complete(self, **kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.calls.append(kwargs)
        return self.completion


def run(completion: Completion) -> StockMessage:
    return extract_text(FakeClient(completion), "texto qualquer", model="fake-model")


def test_valid_output() -> None:
    result = run(Completion('{"product_name": "Parafuso", "stock_level": 40}', "stop", usage=USAGE))

    assert result == StockMessage(product_name="Parafuso", stock_level=40)


def test_missing_field_stays_none() -> None:
    result = run(Completion('{"product_name": "Parafuso", "stock_level": null}', "stop"))

    assert result.stock_level is None


def test_truncated_raises_with_usage() -> None:
    with raises(TruncatedOutputError) as info:
        _ = run(Completion('{"product_name": "Para', "length", usage=USAGE))

    assert info.value.usage == USAGE


def test_refusal_raises() -> None:
    with raises(RefusedError):
        _ = run(Completion(None, "stop", refusal="não posso ajudar"))


def test_empty_content_raises() -> None:
    with raises(InvalidOutputError):
        _ = run(Completion(None, "stop"))


def test_broken_json_raises() -> None:
    with raises(InvalidOutputError):
        _ = run(Completion("isso não é json", "stop"))


def test_wrong_type_raises() -> None:
    with raises(InvalidOutputError):
        _ = run(Completion('{"product_name": "Parafuso", "stock_level": "muito"}', "stop"))


def test_extra_field_raises() -> None:
    with raises(InvalidOutputError):
        _ = run(Completion('{"product_name": "P", "stock_level": 1, "price": 9.9}', "stop"))


def test_all_errors_share_base() -> None:
    with raises(ExtractionError):
        _ = run(Completion("{}", "stop"))


def test_sends_schema_and_params() -> None:
    client = FakeClient(Completion('{"product_name": null, "stock_level": null}', "stop"))

    _ = extract_text(client, "oi", model="fake-model", max_completion_tokens=99)

    call = client.calls[0]
    assert call["model"] == "fake-model"
    assert call["user"] == "oi"
    assert call["max_completion_tokens"] == 99
    assert call["response_schema"]["additionalProperties"] is False
    assert set(call["response_schema"]["required"]) == {"product_name", "stock_level"}  # pyright: ignore[reportAny]
