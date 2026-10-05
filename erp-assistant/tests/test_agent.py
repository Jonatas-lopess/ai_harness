from collections.abc import Sequence
from datetime import date
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
from tools import ToolContext, ToolError, ToolInput, ToolRegistry, ToolSchema, make_tool

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


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            make_tool("echo", "Echo n.", _EchoInput, lambda _ctx, args: _EchoOutput(n=args.n)),
            make_tool("ping", "No arguments.", _NoArgs, lambda _ctx, _args: _Pong(ok=True)),
        ]
    )


def _ctx() -> ToolContext:
    return ToolContext(conn=cast("psycopg.Connection", object()), as_of=AS_OF)


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
    def boom(_ctx: ToolContext, _args: _NoArgs) -> BaseModel:
        raise RuntimeError("db down")

    registry = ToolRegistry([make_tool("boom", "Fails.", _NoArgs, boom)])
    client = ScriptedChat(_call(ToolCall("c1", "boom", "{}")))

    with raises(RuntimeError):
        _ = run_agent(client, registry, _ctx(), model="m", system="s", user="u", max_steps=3)


def test_max_steps_must_be_positive():
    with raises(ValueError):
        _ = _run(ScriptedChat(), max_steps=0)
