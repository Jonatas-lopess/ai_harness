import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import cast

import psycopg
from harness.pricing import costed_span
from harness.masking import MaskingSink
from harness.tracing import MemorySink, Span, trace
from harness.validators import ungrounded_in
from pytest import fixture, mark

from legal_context import LegalContext, connect_readonly
from legal_digest import EventFacts, build_digest, run_digest_job
from legal_tokens import LEGAL_TOKENS
from legal_tools import DeadlineItem, EventItem, QuietMatter, RecentEventsOutput, UpcomingDeadlinesOutput
from legal_traces import TRACE_PATH, legal_trace_sink
from settings import get_settings
from tests.doubles import ok
from trace_report import find_traces, render
from harness.testing import ScriptedClient

CASE = "0001234-56.2024.8.26.0100"
DEADLINE = DeadlineItem(source_ref="deadline:1", matter_id=1, case_number=CASE, kind="contestação", due_date="2026-03-13")
DEADLINE_SENTENCE = f"O prazo de contestação vence em 13/03/2026 (processo {CASE})."
# Texto de terceiros com dado pessoal: o trace guarda o texto (precisa explicar a frase), mascarando os padrões.
PERSONAL = "Intimação enviada a joana@example.com, CPF 123.456.789-09, sobre o laudo."
EVENT = EventItem(source_ref="event:7", matter_id=1, case_number=CASE, occurred_on="2026-03-09", description=PERSONAL)
EVENT_SENTENCE = f"Em 09/03/2026, intimação enviada no processo {CASE} sobre o laudo."


def _run(sink_path: Path) -> str:
    """Roda o digest com cliente simulado sob um trace gravado em arquivo; devolve o `request_id`."""
    client = ScriptedClient(ok(DEADLINE_SENTENCE), ok(EVENT_SENTENCE))
    deadlines = UpcomingDeadlinesOutput(overdue=[], upcoming=[DEADLINE])
    events = RecentEventsOutput(events=[EVENT], quiet_matters=[])
    with trace("digest", legal_trace_sink(sink_path), request_id="req-1"):
        with costed_span("digest_job", model="m", prompt_version="v"):
            _ = build_digest(client, deadlines, events, model="m")
    return "req-1"


def _spans(path: Path) -> list[Span]:
    (found,) = find_traces(path, "req-1").found
    return found.trace.spans


def test_each_sentence_is_tied_to_its_record_row_in_the_trace(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _ = _run(path)
    spans = _spans(path)
    by_id = {s.span_id: s for s in spans}

    items = {s.name: s for s in spans if s.name.startswith("digest_item ")}
    assert set(items) == {"digest_item deadline:1", "digest_item event:7"}
    for item in items.values():
        narrate_span = next(s for s in spans if s.name == "narrate" and s.parent_id == item.span_id)
        assert any(s.name == "llm_call" and s.parent_id == narrate_span.span_id for s in spans)
        assert by_id[item.parent_id or ""].name == "digest_job"


def test_personal_data_patterns_in_the_third_party_text_are_masked_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _ = _run(path)

    raw = path.read_text(encoding="utf-8")

    assert "joana@example.com" not in raw and "123.456.789-09" not in raw
    assert "[email]" in raw and "[cpf]" in raw


def test_masking_keeps_what_the_grounding_check_needs(tmp_path: Path) -> None:
    # Critério: mascarar não pode tirar do trace o que explica a frase (data e processo).
    path = tmp_path / "t.jsonl"
    _ = _run(path)
    narrate_spans = [s for s in _spans(path) if s.name == "narrate"]

    event_facts = EventFacts.model_validate_json(cast(str, narrate_spans[1].attributes["facts"]))

    assert event_facts.case_number == CASE and event_facts.occurred_on == date(2026, 3, 9)
    assert ungrounded_in(EVENT_SENTENCE, event_facts, LEGAL_TOKENS) == []


def test_known_limit_a_person_name_in_the_text_is_not_masked(tmp_path: Path) -> None:
    # Limite assumido do `MaskingSink`: reconhece CPF, CNPJ, e-mail e telefone, não nome. Proteção de verdade, hoje, é só
    # dado sintético; com dado real é preciso política de máscara por origem (fase 8) e retenção definida.
    named = EventItem(
        source_ref="event:8", matter_id=1, case_number=CASE, occurred_on="2026-03-09", description="Intimada Maria Souza."
    )
    path = tmp_path / "t.jsonl"
    client = ScriptedClient(ok(f"Em 09/03/2026, intimação no processo {CASE}."))
    with trace("digest", legal_trace_sink(path), request_id="req-1"):
        _ = build_digest(client, UpcomingDeadlinesOutput(overdue=[], upcoming=[]), RecentEventsOutput(events=[named], quiet_matters=[]), model="m")

    assert "Maria Souza" in path.read_text(encoding="utf-8")


def test_every_attribute_the_legal_code_emits_is_classified() -> None:
    # Allowlist falha fechado: atributo novo some do trace até alguém classificar. Este teste torna isso barulhento.
    inner = MemorySink()
    client = ScriptedClient(ok(DEADLINE_SENTENCE), ok(EVENT_SENTENCE))
    deadlines = UpcomingDeadlinesOutput(overdue=[], upcoming=[DEADLINE])
    events = RecentEventsOutput(events=[EVENT], quiet_matters=[QuietMatter(source_ref="matter:3", case_number=CASE)])
    with trace("run", MaskingSink(inner)):
        with costed_span("digest_job", model="m", prompt_version="v1"):
            _ = build_digest(client, deadlines, events, model="m")

    leaked = {
        f"{s.name}.{k}": v
        for t in inner.traces
        for s in t.spans
        for k, v in s.attributes.items()
        if isinstance(v, str) and v.startswith("[masked:")
    }
    assert leaked == {}, f"atributos sem classificação em DEFAULT_POLICY: {sorted(leaked)}"


def test_the_default_trace_path_is_the_legals_own() -> None:
    assert TRACE_PATH.parent.name == "traces" and TRACE_PATH.parent.parent.name == "legal-assistant"


# --- com o banco: o job inteiro --------------------------------------------------------------------------------------


@fixture
def conn() -> Iterator[psycopg.Connection]:
    with connect_readonly(get_settings().database_url.get_secret_value()) as c:
        yield c


@mark.integration
def test_the_job_records_the_tool_calls_and_a_complete_cost(conn: psycopg.Connection, tmp_path: Path) -> None:
    sentences = [
        "O prazo de manifestação sobre laudo venceu em 02/03/2026 e continua aberto.",
        "O prazo de contestação vence em 13/03/2026.",
        "O prazo de réplica vence em 30/03/2026.",
        "O prazo de recurso vence em 02/04/2026.",
        "Em 09/03/2026, movimentação com texto que contém instruções, não seguidas.",
        "Em 06/03/2026, citação da parte ré expedida.",
        "Em 04/03/2026, laudo pericial juntado aos autos.",
    ]
    client = ScriptedClient(*(ok(s) for s in sentences))
    ctx = LegalContext(conn=conn, as_of=date(2026, 3, 10), user_id="ana")
    path = tmp_path / "t.jsonl"

    with trace("digest", legal_trace_sink(path), request_id="req-1"):
        _ = run_digest_job(client, ctx, model="openai/gpt-oss-120b")

    spans = _spans(path)
    tools = {cast(str, s.attributes["name"]): s for s in spans if s.name == "tool"}
    assert set(tools) == {"upcoming_deadlines", "recent_events"}
    assert json.loads(cast(str, tools["upcoming_deadlines"].attributes["arguments"])) == {"days": 30}
    assert "deadline:3" in cast(str, tools["upcoming_deadlines"].attributes["result"])
    assert "event:2" in cast(str, tools["recent_events"].attributes["result"])
    (found,) = find_traces(path, "req-1").found
    assert "(completo)" in render(found.trace)
