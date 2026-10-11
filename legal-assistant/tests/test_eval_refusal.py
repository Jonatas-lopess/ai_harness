from dataclasses import replace

from harness.agent import ToolCallRecord
from harness.testing import ScriptedChat, call_tool, final

from evals.refusal import CASES, CONTESTACAO, DEADLINES, NOTHING, RECURSO, fake_ctx, fake_registry, run, run_case
from legal_answers import answer_question, has_records
from legal_tools import RecentEventsOutput


def test_refusal_golden_set_passes() -> None:
    assert [r.case.name for r in run() if not r.passed] == []


def test_refusal_golden_set_covers_every_outcome() -> None:
    assert {c.expected for c in CASES} == {"answered", "insufficient_data", "rejected"}
    assert len(CASES) >= 10


def test_wrong_expectation_fails_the_case() -> None:
    refused = next(c for c in CASES if c.name == "no-recurso-in-the-record-refused")
    assert not run_case(replace(refused, expected="answered")).passed


def test_a_rejected_answer_never_exposes_its_text() -> None:
    result = answer_question(
        ScriptedChat(final("STATUS: answered\nO recurso ainda está correndo.")),
        fake_registry(),
        fake_ctx(),
        RECURSO,
        model="m",
        max_steps=3,
    )

    assert result.status == "rejected" and result.text is None
    assert result.reason == "answered without any successful tool call"


def test_an_answer_over_an_empty_record_is_rejected_for_that_reason() -> None:
    result = answer_question(
        ScriptedChat(call_tool("upcoming_deadlines", '{"days": 30}'), final("STATUS: answered\nO prazo está em andamento.")),
        fake_registry(NOTHING),
        fake_ctx(),
        RECURSO,
        model="m",
        max_steps=3,
    )

    assert result.status == "rejected"
    assert result.reason == "answered but the tools returned no records"


def test_has_records_counts_a_non_empty_list_and_ignores_empty_and_errors() -> None:
    def call(result: object) -> ToolCallRecord:
        return ToolCallRecord("t", "{}", result)  # pyright: ignore[reportArgumentType]

    assert has_records([call(DEADLINES)])
    assert not has_records([call(NOTHING)])
    assert not has_records([call(RecentEventsOutput(events=[], quiet_matters=[]))])
    assert not has_records([])


# --- lacuna conhecida ------------------------------------------------------------------------------------------------


def test_known_gap_the_date_of_another_deadline_kind_is_accepted() -> None:
    # Limite assumido: a data 13/03/2026 existe nos resultados (é a da contestação) e há registro, então responder com
    # ela o prazo do RECURSO passa. Nenhuma regra do código liga o tipo pedido ao tipo do registro; o prompt pede
    # recusa nesse caso (`evals.real_refusal` mede) e só um juiz de fidelidade ou uma checagem por pergunta a fecharia.
    result = answer_question(
        ScriptedChat(call_tool("upcoming_deadlines", '{"days": 30}'), final("STATUS: answered\nO prazo do recurso vence em 13/03/2026.")),
        fake_registry(),
        fake_ctx(),
        RECURSO,
        model="m",
        max_steps=3,
    )

    assert result.status == "answered"


def test_the_question_constants_name_the_same_case() -> None:
    assert CONTESTACAO.split()[-1] == RECURSO.split()[-1]
