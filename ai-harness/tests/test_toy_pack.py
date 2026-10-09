"""Critério da fase 5: um pack de outro domínio roda o harness inteiro sem editá-lo.

Cada teste de "esquecimento" mostra o que acontece quando o pack não fornece uma peça: erro alto ou falha silenciosa.
"""

import ast
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from pytest import CaptureFixture, raises
from toy_pack.pack import (
    ALIASES,
    ASK_PROMPT,
    MODEL,
    NARRATE_PROMPT,
    PRICES,
    TOY_NUMBERS,
    TOY_SUITES,
    HelpdeskContext,
    QueueStats,
    Ticket,
    queue_job,
    toy_registry,
)

from harness.agent import AssistantMessage, ChatResponse
from harness.answers import answer_question
from harness.evals import main as evals_main
from harness.llm import Usage
from harness.masking import production_sink
from harness.narrate import narrate
from harness.testing import FixedClient, ScriptedChat, call_tool, final
from harness.trace_report import main as report_main
from harness.tracing import MemorySink, trace

CTX = HelpdeskContext(
    tickets=(Ticket("billing", date(2026, 10, 1)), Ticket("billing", date(2026, 10, 3)), Ticket("sales", date(2026, 10, 2))),
    today=date(2026, 10, 4),
)
GOOD = "A fila billing tem 2 tickets abertos, o mais antigo com 3 dias."


def _priced(text: str) -> ChatResponse:
    return ChatResponse(AssistantMessage(text), "stop", Usage(1000, 500))


def _chat() -> ScriptedChat:
    return ScriptedChat(call_tool("queue_stats", '{"queue": "billing"}'), _priced(f"STATUS: answered\n{GOOD}"))


def test_a_whole_job_runs_on_the_harness_alone_and_the_trace_tells_the_story(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    path = tmp_path / "toy.jsonl"

    with trace("queue_job", production_sink(path), request_id="toy-1"):
        report = queue_job(_chat(), FixedClient(GOOD), CTX, "billing")

    assert (report.answer.status, report.answer.text) == ("answered", GOOD)
    assert report.summary.rationale == GOOD
    assert report_main(["toy-1", "--file", str(path)]) == 0
    story = capsys.readouterr().out
    assert "(completo)" in story and "queue_job" in story and "tool" in story


def test_the_tool_sees_the_packs_context_not_a_database() -> None:
    result = toy_registry().call("queue_stats", CTX, {"queue": "billing"})

    assert result == QueueStats(queue="billing", open_tickets=2, oldest_days=3)


# --- o que acontece quando o pack esquece uma peça -----------------------------------------------------------------


def test_forgetting_the_number_reader_is_a_loud_error_not_a_default() -> None:
    facts = QueueStats(queue="billing", open_tickets=2, oldest_days=3)

    with raises(TypeError, match="reader"):
        narrate(FixedClient(GOOD), facts, system=NARRATE_PROMPT, values={}, aliases=ALIASES, model=MODEL)  # pyright: ignore[reportCallIssue]
    with raises(TypeError, match="reader"):
        answer_question(_chat(), toy_registry(), CTX, "q", system=ASK_PROMPT, model=MODEL, max_steps=3)  # pyright: ignore[reportCallIssue]


def test_forgetting_the_sink_path_is_a_loud_error() -> None:
    with raises(TypeError, match="path"):
        production_sink()  # pyright: ignore[reportCallIssue]


def test_forgetting_the_price_table_is_silent_but_visible_in_the_trace() -> None:
    sink = MemorySink()

    with trace("t", sink):
        report = queue_job(_chat(), FixedClient(GOOD), CTX, "billing", prices=None)

    job = next(s for s in sink.traces[0].spans if s.name == "queue_job")
    assert report.answer.status == "answered"  # o job roda e responde normalmente
    assert job.attributes["cost_complete"] is False and job.attributes["calls_without_cost"] == 3


def test_with_the_price_table_the_cost_is_exact() -> None:
    sink = MemorySink()

    with trace("t", sink):
        _ = queue_job(_chat(), FixedClient(GOOD), CTX, "billing", prices=PRICES)

    job = next(s for s in sink.traces[0].spans if s.name == "queue_job")
    # Só a resposta final do agente tem uso: (1000 * 1 + 500 * 2) / 1e6. A chamada de tool e a do narrate vêm com 0 token.
    assert job.attributes["cost"] == Decimal("0.002") and job.attributes["cost_complete"] is True


def test_running_without_an_active_trace_works_and_writes_nothing(tmp_path: Path) -> None:
    report = queue_job(_chat(), FixedClient(GOOD), CTX, "billing")

    assert report.answer.status == "answered"
    assert list(tmp_path.iterdir()) == []


def test_a_tool_the_model_invents_comes_back_as_an_error_and_the_answer_is_rejected() -> None:
    chat = ScriptedChat(call_tool("delete_everything"), final("STATUS: answered\nFeito."))

    result = answer_question(chat, toy_registry(), CTX, "q", system=ASK_PROMPT, reader=TOY_NUMBERS, model=MODEL, max_steps=3)

    assert result.status == "rejected" and result.reason == "answered without any successful tool call"


def test_a_reply_that_ignores_the_status_protocol_is_rejected() -> None:
    # É o que acontece quando o prompt do pack não pede o formato `STATUS:` (ver `STATUS_PROTOCOL`).
    chat = ScriptedChat(call_tool("queue_stats", '{"queue": "billing"}'), final(GOOD))

    result = answer_question(chat, toy_registry(), CTX, "q", system="prompt sem formato", reader=TOY_NUMBERS, model=MODEL, max_steps=3)

    assert result.status == "rejected" and result.text is None


def test_a_number_the_tool_never_returned_is_rejected_by_the_packs_own_reader() -> None:
    chat = ScriptedChat(call_tool("queue_stats", '{"queue": "billing"}'), final("STATUS: answered\nA fila tem 9 tickets."))

    result = answer_question(chat, toy_registry(), CTX, "q", system=ASK_PROMPT, reader=TOY_NUMBERS, model=MODEL, max_steps=3)

    assert result.reason == "numbers not present in tool results: ['9']"


# --- evals e fronteira ---------------------------------------------------------------------------------------------


def test_the_packs_suite_runs_on_the_harness_runner(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    code = evals_main(["--record"], suites=TOY_SUITES, history_path=tmp_path / "h.jsonl")

    assert code == 0 and "toy: 1/1" in capsys.readouterr().out
    assert (tmp_path / "h.jsonl").exists()


def test_the_toy_pack_imports_only_the_harness_pydantic_and_the_standard_library() -> None:
    allowed = set(sys.stdlib_module_names) | {"pydantic", "harness"}
    tree = ast.parse((Path(__file__).parent / "toy_pack" / "pack.py").read_text())
    roots = {
        n.split(".")[0]
        for node in ast.walk(tree)
        for n in (
            [a.name for a in node.names] if isinstance(node, ast.Import)
            else [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
            else []
        )
    }

    assert roots - allowed == set()
