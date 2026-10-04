import asyncio
import time
from typing import Any, NoReturn

import httpx
from groq import RateLimitError
from pytest import MonkeyPatch, raises

from extract import (
    Completion,
    ExtractionResult,
    InvalidOutputError,
    ProviderUnavailableError,
    StockMessage,
    Usage,
    aextract_with_retry,
    extract_many,
)
from groq_client import AsyncGroqClient

USAGE = Usage(prompt_tokens=10, completion_tokens=5)
GOOD = Completion('{"product_name": "Parafuso", "stock_level": 40}', "stop", usage=USAGE)
BAD = Completion("isso não é json", "stop", usage=USAGE)


class AsyncScriptedClient:
    """Uma resposta (ou erro) por chamada, na ordem."""

    def __init__(self, *items: Completion | Exception) -> None:
        self.items: list[Completion | Exception] = list(items)
        self.calls: int = 0

    async def complete(self, **_kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class SlowClient:
    """Cada chamada espera `delay` segundos de I/O simulado; guarda o pico de chamadas simultâneas."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay: float = delay
        self.in_flight: int = 0
        self.peak: int = 0

    async def complete(self, **_kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        return GOOD


def test_async_retry_succeeds_after_invalid_and_sums_usage() -> None:
    client = AsyncScriptedClient(BAD, GOOD)

    result = asyncio.run(aextract_with_retry(client, "oi", model="m"))

    assert result.value == StockMessage(product_name="Parafuso", stock_level=40)
    assert result.attempts == 2
    assert result.usage == Usage(20, 10)


def test_async_retry_gives_up_after_max_attempts() -> None:
    client = AsyncScriptedClient(BAD, BAD, BAD, GOOD)

    with raises(InvalidOutputError) as info:
        _ = asyncio.run(aextract_with_retry(client, "oi", model="m", max_attempts=3))

    assert client.calls == 3
    assert info.value.usage == Usage(30, 15)


def test_async_provider_unavailable_is_not_retried_and_keeps_usage() -> None:
    client = AsyncScriptedClient(BAD, ProviderUnavailableError("down"), GOOD)

    with raises(ProviderUnavailableError) as info:
        _ = asyncio.run(aextract_with_retry(client, "oi", model="m"))

    assert client.calls == 2
    assert info.value.usage == Usage(10, 5)


def test_extract_many_runs_concurrently() -> None:
    client = SlowClient(delay=0.05)

    start = time.perf_counter()
    results = asyncio.run(extract_many(client, ["x"] * 10, model="m", max_concurrency=10))
    elapsed = time.perf_counter() - start

    assert len(results) == 10
    assert client.peak == 10
    assert elapsed < 0.25  # sequencial levaria ~0,5s


def test_extract_many_caps_concurrency() -> None:
    client = SlowClient()

    _ = asyncio.run(extract_many(client, ["x"] * 10, model="m", max_concurrency=3))

    assert client.peak == 3


def test_extract_many_returns_failure_as_value_and_keeps_order() -> None:
    client = AsyncScriptedClient(GOOD, ProviderUnavailableError("down"), GOOD)

    results = asyncio.run(extract_many(client, ["a", "b", "c"], model="m", max_concurrency=1))

    assert isinstance(results[0], ExtractionResult)
    assert isinstance(results[1], ProviderUnavailableError)
    assert isinstance(results[2], ExtractionResult)


def test_extract_many_rejects_zero_concurrency() -> None:
    with raises(ValueError):
        _ = asyncio.run(extract_many(AsyncScriptedClient(), ["a"], model="m", max_concurrency=0))


def test_async_groq_client_translates_rate_limit(monkeypatch: MonkeyPatch) -> None:
    client = AsyncGroqClient("gsk_fake")
    error = RateLimitError(
        "boom",
        response=httpx.Response(429, request=httpx.Request("POST", "http://test")),
        body=None,
    )

    async def fail(**_kwargs: Any) -> NoReturn:  # pyright: ignore[reportExplicitAny, reportAny]
        raise error

    monkeypatch.setattr(client._client.chat.completions, "create", fail)  # pyright: ignore[reportPrivateUsage]

    with raises(ProviderUnavailableError):
        _ = asyncio.run(
            client.complete(model="m", system="s", user="u", response_schema={}, max_completion_tokens=10)
        )
