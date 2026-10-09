import json

from harness.agent import ToolCall
from harness.llm import Usage
from harness.narrate import Rationale
from harness.testing import FixedClient, ScriptedChat, call_tool, final


def test_fixed_client_answers_in_the_schema_narrate_expects() -> None:
    completion = FixedClient("Há 4 itens.").complete()

    assert Rationale.model_validate_json(completion.content or "").rationale == "Há 4 itens."
    assert completion.usage == Usage(0, 0)


def test_scripted_chat_returns_one_response_per_turn_in_order() -> None:
    chat = ScriptedChat(call_tool("ping"), final("pronto"))

    first = chat.chat(model="m", system="s", messages=[], tools=[], max_completion_tokens=1)
    second = chat.chat(model="m", system="s", messages=[], tools=[], max_completion_tokens=1)

    assert first.message.tool_calls == (ToolCall("c1", "ping", "{}"),)
    assert second.message.content == "pronto" and second.message.tool_calls == ()


def test_fixed_client_content_is_valid_json() -> None:
    assert json.loads(FixedClient("x").complete().content or "") == {"rationale": "x"}
