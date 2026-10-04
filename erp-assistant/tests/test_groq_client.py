from typing import Any, NoReturn

import httpx
from groq import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pytest import MonkeyPatch, mark, raises

from extract import ExtractionError, InvalidOutputError, ProviderUnavailableError
from groq_client import GroqClient


def bad_request(code: str) -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    body = {"error": {"message": "boom", "type": "invalid_request_error", "code": code}}
    return BadRequestError("boom", response=response, body=body)


def make_client(monkeypatch: MonkeyPatch, error: Exception) -> GroqClient:
    client = GroqClient("gsk_fake")

    def fail(**_kwargs: Any) -> NoReturn:  # pyright: ignore[reportAny, reportExplicitAny]
        raise error

    monkeypatch.setattr(client._client.chat.completions, "create", fail)  # pyright: ignore[reportPrivateUsage]
    return client


def complete(client: GroqClient) -> None:
    _ = client.complete(model="m", system="s", user="u", response_schema={}, max_completion_tokens=10)


def test_json_validate_failed_becomes_invalid_output(monkeypatch: MonkeyPatch) -> None:
    client = make_client(monkeypatch, bad_request("json_validate_failed"))

    with raises(InvalidOutputError):
        complete(client)


def test_other_bad_request_passes_through(monkeypatch: MonkeyPatch) -> None:
    client = make_client(monkeypatch, bad_request("something_else"))

    with raises(BadRequestError):
        complete(client)


REQUEST = httpx.Request("POST", "http://test")


def status_error(cls: type[RateLimitError] | type[InternalServerError], status: int) -> Exception:
    return cls("boom", response=httpx.Response(status, request=REQUEST), body=None)


@mark.parametrize(
    "error",
    [
        status_error(RateLimitError, 429),
        status_error(InternalServerError, 503),
        APIConnectionError(request=REQUEST),
        APITimeoutError(request=REQUEST),
    ],
    ids=["429", "5xx", "connection", "timeout"],
)
def test_transient_errors_become_provider_unavailable(monkeypatch: MonkeyPatch, error: Exception) -> None:
    client = make_client(monkeypatch, error)

    with raises(ProviderUnavailableError) as info:
        complete(client)

    assert isinstance(info.value, ExtractionError)
    assert info.value.__cause__ is error


def test_retry_limits_are_passed_to_sdk() -> None:
    client = GroqClient("gsk_fake", max_retries=5, timeout=12.0)

    assert client._client.max_retries == 5  # pyright: ignore[reportPrivateUsage]
    assert client._client.timeout == 12.0  # pyright: ignore[reportPrivateUsage]
