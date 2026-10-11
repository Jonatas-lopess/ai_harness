import json
from collections.abc import Iterator
from datetime import date
from typing import cast

import psycopg
from harness.llm import Usage
from harness.testing import ScriptedClient
from pytest import fixture, mark

from legal_context import LegalContext, connect_readonly
from legal_digest import PROMPT_VERSION, build_digest, run_digest_job
from legal_tools import DeadlineItem, UpcomingDeadlinesOutput
from settings import get_settings
from tests.doubles import USAGE, ok

OVERDUE = DeadlineItem(
    source_ref="deadline:3",
    matter_id=2,
    case_number="0007654-32.2023.8.26.0050",
    kind="manifestação sobre laudo",
    due_date="2026-03-02",
)
UPCOMING = DeadlineItem(
    source_ref="deadline:1",
    matter_id=1,
    case_number="0001234-56.2024.8.26.0100",
    kind="contestação",
    due_date="2026-03-13",
)
DEADLINES = UpcomingDeadlinesOutput(overdue=[OVERDUE], upcoming=[UPCOMING])

SENTENCE_OVERDUE = "O prazo de manifestação sobre laudo venceu em 02/03/2026 e continua aberto (0007654-32.2023.8.26.0050)."
SENTENCE_UPCOMING = "O prazo de contestação vence em 13/03/2026 (0001234-56.2024.8.26.0100)."


def test_the_digest_puts_overdue_first_and_the_code_sets_the_refs() -> None:
    client = ScriptedClient(ok(SENTENCE_OVERDUE), ok(SENTENCE_UPCOMING))

    digest = build_digest(client, DEADLINES, model="m")

    assert [(i.source_ref, i.situation, i.due_date) for i in digest.items] == [
        ("deadline:3", "overdue", "2026-03-02"),
        ("deadline:1", "upcoming", "2026-03-13"),
    ]
    assert [i.sentence for i in digest.items] == [SENTENCE_OVERDUE, SENTENCE_UPCOMING]
    assert all(i.warning is None for i in digest.items)
    assert digest.usage == Usage(20, 10) and digest.prompt_version == PROMPT_VERSION


def test_each_call_sends_only_the_facts_of_its_own_row_and_no_ids() -> None:
    client = ScriptedClient(ok(SENTENCE_OVERDUE), ok(SENTENCE_UPCOMING))

    _ = build_digest(client, DEADLINES, model="m")

    sent = [cast(dict[str, str], json.loads(cast(str, c["user"]))) for c in client.calls]
    assert [set(s) for s in sent] == [{"kind", "due_date", "case_number", "situation"}] * 2
    assert [s["due_date"] for s in sent] == ["2026-03-02", "2026-03-13"]
    assert all("deadline:" not in c["user"] and "matter_id" not in c["user"] for c in client.calls)


def test_a_wrong_date_is_sent_back_with_the_reason_and_the_retry_is_accepted() -> None:
    wrong = SENTENCE_UPCOMING.replace("13/03", "14/03")
    client = ScriptedClient(ok(SENTENCE_UPCOMING.replace("13/03", "14/03")), ok(SENTENCE_UPCOMING))

    digest = build_digest(client, UpcomingDeadlinesOutput(overdue=[], upcoming=[UPCOMING]), model="m")

    assert digest.items[0].sentence == SENTENCE_UPCOMING
    assert "14/03/2026" in client.calls[1]["user"] and wrong not in client.calls[1]["user"]


def test_a_sentence_that_never_passes_degrades_to_the_record_data_with_a_warning() -> None:
    wrong = SENTENCE_OVERDUE.replace("02/03", "03/03")
    client = ScriptedClient(ok(wrong), ok(wrong), ok(wrong), ok(SENTENCE_UPCOMING))

    digest = build_digest(client, DEADLINES, model="m")

    bad, good = digest.items
    assert bad.sentence is None
    assert bad.warning is not None and "rejected after 3 attempts" in bad.warning and "03/03/2026" in bad.warning
    assert (bad.source_ref, bad.due_date, bad.kind, bad.case_number) == (
        "deadline:3",
        "2026-03-02",
        "manifestação sobre laudo",
        "0007654-32.2023.8.26.0050",
    )
    assert good.sentence == SENTENCE_UPCOMING and good.warning is None  # o digest não cai por um item
    assert len(client.calls) == 4


def test_the_model_cannot_assert_a_ref_in_the_sentence() -> None:
    forged = SENTENCE_UPCOMING + " (deadline:17)"
    client = ScriptedClient(ok(forged), ok(SENTENCE_UPCOMING))

    digest = build_digest(client, UpcomingDeadlinesOutput(overdue=[], upcoming=[UPCOMING]), model="m")

    assert "17" in client.calls[1]["user"]
    assert digest.items[0].sentence == SENTENCE_UPCOMING


def test_a_derived_number_is_rejected() -> None:
    client = ScriptedClient(ok(SENTENCE_UPCOMING + " Faltam 3 dias."), ok(SENTENCE_UPCOMING))

    digest = build_digest(client, UpcomingDeadlinesOutput(overdue=[], upcoming=[UPCOMING]), model="m")

    assert digest.items[0].sentence == SENTENCE_UPCOMING and len(client.calls) == 2


def test_no_deadlines_never_calls_the_model() -> None:
    client = ScriptedClient()

    digest = build_digest(client, UpcomingDeadlinesOutput(overdue=[], upcoming=[]), model="m")

    assert digest.items == [] and client.calls == [] and digest.usage == Usage(0, 0)


# --- com o banco (seed) ---------------------------------------------------------------------------------------------


@fixture
def conn() -> Iterator[psycopg.Connection]:
    with connect_readonly(get_settings().database_url.get_secret_value()) as c:
        yield c


@mark.integration
def test_the_job_reads_the_record_for_the_current_user_only(conn: psycopg.Connection) -> None:
    # Seed da ana (`as_of` 2026-03-10): 3 vencido; 1, 4, 2 por data. O 5 é do bruno.
    sentences = [
        "O prazo de manifestação sobre laudo venceu em 02/03/2026 e continua aberto.",
        "O prazo de contestação vence em 13/03/2026.",
        "O prazo de réplica vence em 30/03/2026.",
        "O prazo de recurso vence em 02/04/2026.",
    ]
    client = ScriptedClient(*(ok(s) for s in sentences))
    ctx = LegalContext(conn=conn, as_of=date(2026, 3, 10), user_id="ana")

    digest = run_digest_job(client, ctx, model="m")

    assert [i.source_ref for i in digest.items] == ["deadline:3", "deadline:1", "deadline:4", "deadline:2"]
    assert all(i.warning is None for i in digest.items)
    assert digest.usage == Usage(USAGE.prompt_tokens * 4, USAGE.completion_tokens * 4)
