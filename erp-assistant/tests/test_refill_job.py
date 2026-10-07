from typing import Any, cast

from pytest import raises

from extract import Completion, ProviderUnavailableError, Usage
from refill_job import (
    MAX_COMPLETION_TOKENS,
    Rationale,
    RefillFacts,
    explain,
)

USAGE = Usage(prompt_tokens=10, completion_tokens=5)
FACTS = RefillFacts(
    product_id=1, name="Parafuso", on_hand=3, open_po_qty=0, reorder_point=40, suggested_qty=250
)


class ScriptedClient:
    """Devolve uma resposta por chamada, na ordem; guarda os argumentos de cada chamada."""

    def __init__(self, *completions: Completion | Exception) -> None:
        self.completions: list[Completion | Exception] = list(completions)
        self.calls: list[dict[str, Any]] = []  # pyright: ignore[reportExplicitAny]

    def complete(self, **kwargs: Any) -> Completion:  # pyright: ignore[reportExplicitAny, reportAny]
        self.calls.append(kwargs)
        nxt = self.completions.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def ok(text: str) -> Completion:
    return Completion(f'{{"rationale": "{text}"}}', "stop", usage=USAGE)


def test_grounded_rationale_is_accepted() -> None:
    client = ScriptedClient(ok("Estoque 3 abaixo do ponto 40; repor 250."))

    result = explain(client, FACTS, model="m")

    assert result.rationale == "Estoque 3 abaixo do ponto 40; repor 250."
    assert result.error is None
    assert result.attempts == 1


def test_schema_has_only_the_rationale_field() -> None:
    # O modelo não tem onde escrever a quantidade: ela só existe no que o código monta.
    client = ScriptedClient(ok("Repor 250."))

    _ = explain(client, FACTS, model="m")

    schema = Rationale.model_json_schema()
    assert client.calls[0]["response_schema"] == schema
    assert list(cast(dict[str, object], schema["properties"])) == ["rationale"]
    assert client.calls[0]["max_completion_tokens"] == MAX_COMPLETION_TOKENS


def test_facts_go_in_the_prompt_as_json() -> None:
    client = ScriptedClient(ok("Repor 250."))

    _ = explain(client, FACTS, model="m")

    assert client.calls[0]["user"] == FACTS.model_dump_json()


def test_invented_number_is_retried_with_feedback() -> None:
    client = ScriptedClient(
        ok("Repor 250; o fornecedor leva 12 dias."),
        ok("Repor 250."),
    )

    result = explain(client, FACTS, model="m")

    assert result.rationale == "Repor 250."
    assert result.attempts == 2
    assert "['12']" in client.calls[1]["user"]
    assert result.usage == Usage(20, 10)


def test_number_on_the_wrong_field_is_retried_with_feedback() -> None:
    # 40 e 3 existem nos fatos, mas estão trocados: o validador de "existe?" não pega.
    client = ScriptedClient(
        ok("O estoque atual é 40, abaixo do ponto de 3."),
        ok("O estoque atual é 3, abaixo do ponto de 40."),
    )

    result = explain(client, FACTS, model="m")

    assert result.rationale == "O estoque atual é 3, abaixo do ponto de 40."
    assert result.attempts == 2
    assert "wrong field" in client.calls[1]["user"]
    assert "'on_hand'" in client.calls[1]["user"]


def test_number_from_another_item_is_rejected() -> None:
    # 240 é a quantidade de outro produto: só os fatos DESTE item contam como origem.
    client = ScriptedClient(ok("Repor 240."), ok("Repor 240."), ok("Repor 240."))

    result = explain(client, FACTS, model="m")

    assert result.rationale is None


def test_item_degrades_after_max_attempts() -> None:
    client = ScriptedClient(ok("Repor 99."), ok("Repor 98."))

    result = explain(client, FACTS, model="m", max_attempts=2)

    assert result.rationale is None
    assert result.error is not None and "after 2 attempts" in result.error
    assert result.attempts == 2
    assert len(client.calls) == 2


def test_blank_rationale_is_invalid() -> None:
    client = ScriptedClient(ok("   "), ok("Repor 250."))

    assert explain(client, FACTS, model="m").rationale == "Repor 250."


def test_truncated_output_degrades_without_retry() -> None:
    client = ScriptedClient(Completion('{"rationale": "Repor', "length", usage=USAGE))

    result = explain(client, FACTS, model="m")

    assert result.rationale is None
    assert result.error is not None and "cut at max_completion_tokens" in result.error
    assert len(client.calls) == 1


def test_provider_failure_propagates_with_accumulated_usage() -> None:
    client = ScriptedClient(ok("Repor 99."), ProviderUnavailableError("down"))

    with raises(ProviderUnavailableError) as info:
        _ = explain(client, FACTS, model="m")

    assert info.value.usage == USAGE


def test_max_attempts_must_be_positive() -> None:
    with raises(ValueError):
        _ = explain(ScriptedClient(), FACTS, model="m", max_attempts=0)
