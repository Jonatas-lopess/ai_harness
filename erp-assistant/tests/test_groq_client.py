from typing import Any, NoReturn

import httpx
from groq import BadRequestError
from pytest import MonkeyPatch, raises

from extract import InvalidOutputError
from groq_client import GroqClient


def bad_request(code: str) -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    body = {"error": {"message": "boom", "type": "invalid_request_error", "code": code}}
    return BadRequestError("boom", response=response, body=body)


def make_client(monkeypatch: MonkeyPatch, error: BadRequestError) -> GroqClient:
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
