import re
from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel

from harness.agent import AgentResult, ToolCallRecord
from harness.answers import STATUS_PROTOCOL, judge
from harness.llm import Usage
from harness.tools import ToolError
from harness.validators import NumberToken


class _Ints:
    def find(self, text: str) -> Sequence[NumberToken]:
        return [
            NumberToken(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())}))
            for m in re.finditer(r"(?<![\w.])\d+(?!\w)", text)
        ]


class _Open(BaseModel):
    open_items: int


def _agent(text: str, *records: ToolCallRecord) -> AgentResult:
    return AgentResult(text, Usage(0, 0), 1, tuple(records))


OK = ToolCallRecord("count", "{}", _Open(open_items=4))


def test_answered_with_a_grounded_number_and_a_tool_result_is_accepted() -> None:
    result = judge(_agent("STATUS: answered\nHá 4 itens.", OK), _Ints())

    assert (result.status, result.text, result.reason) == ("answered", "Há 4 itens.", None)


def test_a_number_the_tools_never_returned_is_rejected() -> None:
    result = judge(_agent("STATUS: answered\nHá 5 itens.", OK), _Ints())

    assert result.status == "rejected" and result.text is None
    assert result.reason == "numbers not present in tool results: ['5']"


def test_answered_without_any_successful_tool_call_is_rejected() -> None:
    failed = ToolCallRecord("count", "{}", ToolError(error="boom"))

    result = judge(_agent("STATUS: answered\nSem números.", failed), _Ints())

    assert result.reason == "answered without any successful tool call"


def test_insufficient_data_needs_no_tool_evidence() -> None:
    result = judge(_agent("STATUS: insufficient_data\nNenhuma tool traz isso."), _Ints())

    assert result.status == "insufficient_data"


def test_a_reply_without_the_status_header_is_rejected() -> None:
    result = judge(_agent("Há 4 itens.", OK), _Ints())

    assert result.status == "rejected" and result.reason is not None


def test_unknown_status_is_rejected_and_named() -> None:
    result = judge(_agent("STATUS: maybe\nTalvez.", OK), _Ints())

    assert result.reason == "unknown status 'maybe'"


def test_the_protocol_text_names_the_statuses_the_parser_accepts() -> None:
    assert "STATUS: answered" in STATUS_PROTOCOL and "STATUS: insufficient_data" in STATUS_PROTOCOL
