from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast

import psycopg
from pydantic import BaseModel
from pytest import raises

from agent import (
    AssistantMessage,
    BudgetExceededError,
    ChatResponse,
    Message,
    ToolCall,
    ToolMessage,
    UserMessage,
    run_agent,
)
from extract import InvalidOutputError, ProviderUnavailableError, TruncatedOutputError, Usage
from harness.tools import ToolError, ToolInput, ToolRegistry, ToolSchema, make_tool
from erp_context import ErpContext
from harness.tracing import MemorySink, span, trace

AS_OF = date(2026, 1, 31)
USAGE = Usage(prompt_tokens=10, completion_tokens=5)


class _EchoInput(ToolInput):
    n: int


class _EchoOutput(BaseModel):
    n: int


class _NoArgs(ToolInput):
    pass


class _Pong(BaseModel):
    ok: bool


def _registry() -> ToolRegistry[ErpContext]:
    return ToolRegistry(
        [
            make_tool("echo", "Echo n.", _EchoInput, lambda _ctx, args: _EchoOutput(n=args.n)),
            make_tool("ping", "No arguments.", _NoArgs, lambda _ctx, _args: _Pong(ok=True)),
        ]
    )


def _ctx() -> ErpContext:
    return ErpContext(conn=cast("psycopg.Connection", object()), as_of=AS_OF)


class ScriptedChat:
    """Devolve uma resposta por chamada e guarda uma CÓPIA do histórico que recebeu em cada uma."""

    def __init__(self, *responses: ChatResponse | Exception) -> None:
        self._responses: list[ChatResponse | Exception] = list(responses)
        self.histories: list[list[Message]] = []
        self.tools_seen: list[Sequence[ToolSchema]] = []

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_completion_tokens: int,
    ) -> ChatResponse:
        del model, system, max_completion_tokens  # só o histórico e as tools interessam aos testes
        self.histories.append(list(messages))
        self.tools_seen.append(tools)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _answer(text: str, usage: Usage | None = USAGE) -> ChatResponse:
    return ChatResponse(AssistantMessage(text), "stop", usage)


def _call(*calls: ToolCall, usage: Usage | None = USAGE) -> ChatResponse:
    return ChatResponse(AssistantMessage(None, tuple(calls)), "tool_calls", usage)


def _run(client: ScriptedChat, max_steps: int = 5):
    return run_agent(client, _registry(), _ctx(), model="m", system="s", user="pergunta", max_steps=max_steps)


def test_answer_without_tools_ends_in_one_step():
    result = _run(ScriptedChat(_answer("pronto")))

    assert result.text == "pronto"
    assert result.steps == 1
    assert result.tool_calls == ()


def test_tool_result_goes_back_to_the_model():
    client = ScriptedChat(_call(ToolCall("c1", "echo", '{"n": 7}')), _answer("sete"))

    result = _run(client)

    assert result.text == "sete"
    assert result.steps == 2
    [record] = result.tool_calls
    assert record.name == "echo"
    assert record.result == _EchoOutput(n=7)
    # 2ª chamada: pergunta + pedido do assistente + resultado da tool
    assert client.histories[1] == [
        UserMessage("pergunta"),
        AssistantMessage(None, (ToolCall("c1", "echo", '{"n": 7}'),)),
        ToolMessage("c1", '{"n":7}'),
    ]


def test_each_call_resends_the_whole_history():
    client = ScriptedChat(
        _call(ToolCall("c1", "ping", "{}")),
        _call(ToolCall("c2", "ping", "{}")),
        _answer("fim"),
    )

    _ = _run(client)

    assert [len(h) for h in client.histories] == [1, 3, 5]


def test_usage_is_summed_across_steps():
    client = ScriptedChat(_call(ToolCall("c1", "ping", "{}")), _answer("ok"))

    result = _run(client)

    assert result.usage == Usage(20, 10)


def test_schemas_are_sent_on_every_call():
    client = ScriptedChat(_call(ToolCall("c1", "ping", "{}")), _answer("ok"))

    _ = _run(client)

    assert [[t["name"] for t in tools] for tools in client.tools_seen] == [["echo", "ping"]] * 2


def test_broken_json_arguments_become_tool_error_and_loop_continues():
    client = ScriptedChat(_call(ToolCall("c1", "echo", '{"n": 7')), _answer("corrigi"))

    result = _run(client)

    [record] = result.tool_calls
    assert isinstance(record.result, ToolError)
    assert "not valid JSON" in record.result.error
    assert result.text == "corrigi"


def test_non_object_arguments_become_tool_error():
    result = _run(ScriptedChat(_call(ToolCall("c1", "echo", "[1, 2]")), _answer("ok")))

    [record] = result.tool_calls
    assert isinstance(record.result, ToolError)
    assert "JSON object" in record.result.error


def test_blank_arguments_mean_no_arguments():
    result = _run(ScriptedChat(_call(ToolCall("c1", "ping", "")), _answer("ok")))

    [record] = result.tool_calls
    assert record.result == _Pong(ok=True)


def test_unknown_tool_becomes_tool_error():
    result = _run(ScriptedChat(_call(ToolCall("c1", "delete_all", "{}")), _answer("ok")))

    [record] = result.tool_calls
    assert isinstance(record.result, ToolError)
    assert "echo" in record.result.error


def test_every_parallel_tool_call_gets_an_answer():
    client = ScriptedChat(
        _call(ToolCall("a", "echo", '{"n": 1}'), ToolCall("b", "echo", '{"n": 2}')),
        _answer("ok"),
    )

    result = _run(client)

    answered = [m.tool_call_id for m in client.histories[1] if isinstance(m, ToolMessage)]
    assert answered == ["a", "b"]
    assert len(result.tool_calls) == 2


def test_budget_exhausted_raises_with_usage_and_calls():
    client = ScriptedChat(*[_call(ToolCall(f"c{i}", "ping", "{}")) for i in range(3)])

    with raises(BudgetExceededError) as info:
        _ = _run(client, max_steps=3)

    assert info.value.usage == Usage(30, 15)  # o custo gasto não se perde
    assert len(info.value.tool_calls) == 3
    assert len(client.histories) == 3  # parou no teto: nenhuma 4ª chamada


def test_provider_error_carries_usage_accumulated_so_far():
    client = ScriptedChat(_call(ToolCall("c1", "ping", "{}")), ProviderUnavailableError("down"))

    with raises(ProviderUnavailableError) as info:
        _ = _run(client)

    assert info.value.usage == USAGE


def test_truncated_final_answer_raises():
    client = ScriptedChat(ChatResponse(AssistantMessage("meio da fra"), "length", USAGE))

    with raises(TruncatedOutputError) as info:
        _ = _run(client)

    assert info.value.usage == USAGE


def test_empty_final_answer_raises():
    with raises(InvalidOutputError):
        _ = _run(ScriptedChat(ChatResponse(AssistantMessage(None), "stop", USAGE)))


def test_bug_inside_a_tool_is_not_swallowed():
    def boom(_ctx: ErpContext, _args: _NoArgs) -> BaseModel:
        raise RuntimeError("db down")

    registry = ToolRegistry([make_tool("boom", "Fails.", _NoArgs, boom)])
    client = ScriptedChat(_call(ToolCall("c1", "boom", "{}")))

    with raises(RuntimeError):
        _ = run_agent(client, registry, _ctx(), model="m", system="s", user="u", max_steps=3)


def test_max_steps_must_be_positive():
    with raises(ValueError):
        _ = _run(ScriptedChat(), max_steps=0)


def _traced(client: ScriptedChat, max_steps: int = 5) -> MemorySink:
    sink = MemorySink()
    with trace("job", sink, request_id="req-1"):
        try:
            _ = _run(client, max_steps)
        except Exception:
            pass
    return sink


def test_trace_has_one_llm_call_per_step_and_one_tool_span_per_call():
    sink = _traced(ScriptedChat(_call(ToolCall("c1", "echo", '{"n": 7}')), _answer("sete")))

    [t] = sink.traces
    assert [s.name for s in t.spans] == ["job", "agent", "llm_call", "tool", "llm_call"]
    root, agent, llm1, tool, llm2 = t.spans
    assert {llm1.parent_id, tool.parent_id, llm2.parent_id} == {agent.span_id}
    assert agent.parent_id == root.span_id
    assert agent.attributes["system"] == "s"
    assert agent.attributes["user"] == "pergunta"
    assert agent.attributes["steps"] == 2
    assert llm1.attributes["prompt_tokens"] == 10
    assert llm1.attributes["finish_reason"] == "tool_calls"
    assert llm1.attributes["tool_calls"] == [{"id": "c1", "name": "echo", "arguments": '{"n": 7}'}]
    assert llm2.attributes["content"] == "sete"
    assert tool.attributes["name"] == "echo"
    assert tool.attributes["arguments"] == '{"n": 7}'
    assert tool.attributes["result"] == '{"n":7}'
    assert tool.attributes["tool_error"] is False


def test_llm_call_spans_store_only_the_new_output_not_the_whole_history():
    sink = _traced(ScriptedChat(*[_call(ToolCall(f"c{i}", "ping", "{}")) for i in range(2)], _answer("fim")))

    [t] = sink.traces
    llm = [s for s in t.spans if s.name == "llm_call"]
    assert [s.attributes["content"] for s in llm] == [None, None, "fim"]
    assert not any("messages" in s.attributes or "prompt" in s.attributes for s in llm)


def test_agent_span_records_the_tool_schemas_sent_once():
    chat = ScriptedChat(_call(ToolCall("c1", "echo", '{"n": 7}')), _answer("sete"))
    sink = _traced(chat)

    [t] = sink.traces
    agent = next(s for s in t.spans if s.name == "agent")
    assert agent.attributes["tools"] == list(chat.tools_seen[0])
    assert [s.attributes for s in t.spans if s.name == "llm_call" and "tools" in s.attributes] == []


def test_tool_error_is_flagged_but_the_span_stays_ok():
    sink = _traced(ScriptedChat(_call(ToolCall("c1", "delete_all", "{}")), _answer("ok")))

    [t] = sink.traces
    [tool] = [s for s in t.spans if s.name == "tool"]
    assert tool.attributes["tool_error"] is True
    assert tool.status == "ok"
    assert "unknown tool" in str(tool.attributes["result"])


def test_provider_failure_marks_the_llm_call_span_with_the_cause():
    sink = _traced(ScriptedChat(ProviderUnavailableError("fora do ar", Usage(0, 0))))

    [t] = sink.traces
    [llm] = [s for s in t.spans if s.name == "llm_call"]
    assert llm.status == "error"
    assert llm.error is not None and "fora do ar" in llm.error
    assert llm.duration_ms is not None


def test_budget_exhaustion_shows_in_the_agent_span():
    sink = _traced(ScriptedChat(*[_call(ToolCall(f"c{i}", "ping", "{}")) for i in range(3)]), max_steps=3)

    [t] = sink.traces
    [agent] = [s for s in t.spans if s.name == "agent"]
    assert agent.status == "error"
    assert agent.error is not None and "no final answer after 3 steps" in agent.error


def test_agent_runs_the_same_without_an_active_trace():
    with span("outside"):  # sem trace: nada é gravado e nada quebra
        result = _run(ScriptedChat(_answer("pronto")))
    assert result.text == "pronto"


def test_llm_call_spans_carry_cost_from_the_price_table():
    client = ScriptedChat(_call(ToolCall("c1", "ping", "{}")), _answer("ok"))
    sink = MemorySink()
    with trace("job", sink):
        _ = run_agent(client, _registry(), _ctx(), model="openai/gpt-oss-120b", system="s", user="u", max_steps=5)

    llm = [s for s in sink.traces[0].spans if s.name == "llm_call"]
    assert [s.attributes["cost"] for s in llm] == [Decimal("0.0000045")] * 2  # 10*0.15 + 5*0.60, por milhão
    assert llm[0].attributes["prices_as_of"] == "2026-10-04"
