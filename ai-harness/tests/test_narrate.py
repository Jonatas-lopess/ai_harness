import json
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from harness.llm import Completion, Usage
from harness.narrate import narrate
from harness.tracing import MemorySink, trace
from harness.validators import NumberToken


class _Ints:
    def find(self, text: str) -> Sequence[NumberToken]:
        return [
            NumberToken(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())}))
            for m in re.finditer(r"(?<![\w.])\d+(?!\w)", text)
        ]


class _Facts(BaseModel):
    """Fatos de um domínio qualquer, sem relação com ERP."""

    open_items: int
    oldest_days: int


FACTS = _Facts(open_items=4, oldest_days=12)
VALUES = {"open_items": 4, "oldest_days": 12}
ALIASES = {"open_items": ("itens",), "oldest_days": ("dias",)}


class _Scripted:
    def __init__(self, *texts: str) -> None:
        self.texts: list[str] = list(texts)
        self.users: list[str] = []

    def complete(self, **kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.users.append(kwargs["user"])  # pyright: ignore[reportAny]
        return Completion(json.dumps({"rationale": self.texts.pop(0)}), "stop", usage=Usage(10, 5))


def _run(client: _Scripted, max_attempts: int = 3):
    return narrate(
        client, FACTS, system="s", values=VALUES, aliases=ALIASES, reader=_Ints(), model="m", max_attempts=max_attempts
    )


def test_a_text_that_only_uses_the_facts_is_accepted_on_the_first_try() -> None:
    result = _run(_Scripted("Há 4 itens abertos, o mais antigo com 12 dias."))

    assert result.rationale == "Há 4 itens abertos, o mais antigo com 12 dias."
    assert result.attempts == 1


def test_an_invented_number_is_sent_back_with_the_reason_and_the_second_text_is_used() -> None:
    client = _Scripted("Há 7 itens.", "Há 4 itens.")

    result = _run(client)

    assert result.rationale == "Há 4 itens." and result.attempts == 2
    assert "numbers not present in the facts: ['7']" in client.users[1]
    assert result.usage == Usage(20, 10)


def test_a_number_on_the_wrong_field_is_rejected_after_the_attempts_run_out() -> None:
    result = _run(_Scripted("Há 12 itens."), max_attempts=1)

    assert result.rationale is None
    assert result.error is not None and "wrong field" in result.error


def test_the_outcome_is_in_the_trace() -> None:
    sink = MemorySink()
    with trace("t", sink):
        _ = _run(_Scripted("Há 4 itens."))

    narrate_span = next(s for s in sink.traces[0].spans if s.name == "narrate")
    assert narrate_span.attributes["outcome"] == "accepted"
