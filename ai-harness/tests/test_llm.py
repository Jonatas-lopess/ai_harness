from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from pytest import raises

from harness.llm import (
    Completion,
    ExtractionError,
    InvalidOutputError,
    ProviderUnavailableError,
    RefusedError,
    TruncatedOutputError,
    Usage,
    add_usage,
    parse_completion,
    with_feedback,
)

USAGE = Usage(prompt_tokens=10, completion_tokens=5)


class _Out(BaseModel):
    """Schema qualquer, sem relação com ERP: o parser não pode depender do conteúdo."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    title: str
    count: int | None


def test_valid_output() -> None:
    result = parse_completion(Completion('{"title": "x", "count": 3}', "stop", usage=USAGE), _Out)

    assert result == _Out(title="x", count=3)


def test_null_field_stays_none() -> None:
    assert parse_completion(Completion('{"title": "x", "count": null}', "stop"), _Out).count is None


def test_truncated_raises_with_usage() -> None:
    with raises(TruncatedOutputError) as info:
        _ = parse_completion(Completion('{"title": "x', "length", usage=USAGE), _Out)

    assert info.value.usage == USAGE


def test_refusal_raises() -> None:
    with raises(RefusedError, match="cannot help"):
        _ = parse_completion(Completion(None, "stop", refusal="cannot help"), _Out)


def test_empty_content_raises() -> None:
    with raises(InvalidOutputError, match="empty output"):
        _ = parse_completion(Completion(None, "stop"), _Out)


def test_broken_json_raises() -> None:
    with raises(InvalidOutputError, match="does not match schema"):
        _ = parse_completion(Completion("not json", "stop"), _Out)


def test_wrong_type_raises_and_names_the_field() -> None:
    with raises(InvalidOutputError, match="count"):
        _ = parse_completion(Completion('{"title": "x", "count": "many"}', "stop"), _Out)


def test_extra_field_raises() -> None:
    with raises(InvalidOutputError, match="price"):
        _ = parse_completion(Completion('{"title": "x", "count": 1, "price": 9.9}', "stop"), _Out)


def test_invalid_output_keeps_the_usage_of_that_call() -> None:
    with raises(InvalidOutputError) as info:
        _ = parse_completion(Completion("{}", "stop", usage=USAGE), _Out)

    assert info.value.usage == USAGE


def test_all_errors_share_a_base() -> None:
    for error in (TruncatedOutputError, RefusedError, InvalidOutputError, ProviderUnavailableError):
        assert issubclass(error, ExtractionError)


def test_add_usage_sums_and_ignores_missing() -> None:
    assert add_usage(USAGE, Usage(1, 2)) == Usage(11, 7)
    assert add_usage(USAGE, None) == USAGE


def test_feedback_keeps_the_original_text_and_the_reason() -> None:
    text = with_feedback("original request", InvalidOutputError("numbers not in facts: ['7']"))

    assert text.startswith("original request")
    assert "numbers not in facts: ['7']" in text
