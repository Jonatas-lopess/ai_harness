from datetime import date
from typing import cast

import psycopg
from pydantic import BaseModel
from pytest import mark, raises

from settings import get_settings
from tools import (
    Tool,
    ToolContext,
    ToolError,
    ToolInput,
    ToolRegistry,
    connect_readonly,
    make_tool,
)

AS_OF = date(2026, 1, 31)


class _EchoInput(ToolInput):
    n: int


class _EchoOutput(BaseModel):
    n: int


def _echo_tool(name: str = "echo") -> Tool:
    return make_tool(name, "Echo n.", _EchoInput, lambda _ctx, args: _EchoOutput(n=args.n))


def _ctx_without_db() -> ToolContext:
    # Essas tools não tocam no banco: a conexão nunca é usada.
    return ToolContext(conn=cast("psycopg.Connection", object()), as_of=AS_OF)


def test_schema_has_name_description_and_parameters():
    [schema] = ToolRegistry([_echo_tool()]).schemas()

    assert schema["name"] == "echo"
    assert schema["description"] == "Echo n."
    assert schema["parameters"]["required"] == ["n"]


def test_valid_call_runs_the_function():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx_without_db(), {"n": 3})

    assert result == _EchoOutput(n=3)


def test_wrong_type_becomes_tool_error_not_exception():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx_without_db(), {"n": "abc"})

    assert isinstance(result, ToolError)
    assert result.error.startswith("invalid arguments: n:")


def test_invented_argument_is_rejected():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx_without_db(), {"n": 1, "force": True})

    assert isinstance(result, ToolError)
    assert "force" in result.error


def test_unknown_tool_lists_available_ones():
    result = ToolRegistry([_echo_tool()]).call("nope", _ctx_without_db(), {})

    assert isinstance(result, ToolError)
    assert "echo" in result.error


def test_duplicate_tool_name_is_a_programming_error():
    with raises(ValueError, match="duplicate"):
        _ = ToolRegistry([_echo_tool(), _echo_tool()])


def test_exception_from_the_tool_itself_is_not_swallowed():
    def boom(_ctx: ToolContext, _args: _EchoInput) -> BaseModel:
        raise RuntimeError("db down")

    registry = ToolRegistry([make_tool("boom", "Fails.", _EchoInput, boom)])

    with raises(RuntimeError):
        _ = registry.call("boom", _ctx_without_db(), {"n": 1})


@mark.integration
def test_readonly_connection_rejects_writes():
    with raises(psycopg.errors.ReadOnlySqlTransaction) and connect_readonly(get_settings().database_url.get_secret_value()) as conn:
        _ = conn.execute("UPDATE products SET stock = 0")
