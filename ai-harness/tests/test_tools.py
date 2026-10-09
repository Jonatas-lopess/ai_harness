from dataclasses import dataclass

from pydantic import BaseModel
from pytest import raises

from harness.tools import Tool, ToolError, ToolInput, ToolRegistry, make_tool


@dataclass(frozen=True)
class _Ctx:
    """Contexto de teste sem banco e sem nada de ERP: prova que o harness aceita qualquer tipo."""

    tenant: str


class _EchoInput(ToolInput):
    n: int


class _EchoOutput(BaseModel):
    n: int


def _echo_tool(name: str = "echo") -> Tool[_Ctx]:
    return make_tool(name, "Echo n.", _EchoInput, lambda _ctx, args: _EchoOutput(n=args.n))


def _ctx() -> _Ctx:
    return _Ctx(tenant="t1")


def test_schema_has_name_description_and_parameters():
    [schema] = ToolRegistry([_echo_tool()]).schemas()

    assert schema["name"] == "echo"
    assert schema["description"] == "Echo n."
    assert schema["parameters"]["required"] == ["n"]


def test_valid_call_runs_the_function():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx(), {"n": 3})

    assert result == _EchoOutput(n=3)


def test_wrong_type_becomes_tool_error_not_exception():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx(), {"n": "abc"})

    assert isinstance(result, ToolError)
    assert result.error.startswith("invalid arguments: n:")


def test_invented_argument_is_rejected():
    result = ToolRegistry([_echo_tool()]).call("echo", _ctx(), {"n": 1, "force": True})

    assert isinstance(result, ToolError)
    assert "force" in result.error


def test_unknown_tool_lists_available_ones():
    result = ToolRegistry([_echo_tool()]).call("nope", _ctx(), {})

    assert isinstance(result, ToolError)
    assert "echo" in result.error


def test_duplicate_tool_name_is_a_programming_error():
    with raises(ValueError, match="duplicate"):
        _ = ToolRegistry([_echo_tool(), _echo_tool()])


def test_exception_from_the_tool_itself_is_not_swallowed():
    def boom(_ctx: _Ctx, _args: _EchoInput) -> BaseModel:
        raise RuntimeError("db down")

    registry = ToolRegistry([make_tool("boom", "Fails.", _EchoInput, boom)])

    with raises(RuntimeError):
        _ = registry.call("boom", _ctx(), {"n": 1})



def test_the_tool_receives_the_exact_context_object_it_was_called_with():
    seen: list[_Ctx] = []

    def spy(ctx: _Ctx, _args: _EchoInput) -> BaseModel:
        seen.append(ctx)
        return _EchoOutput(n=0)

    ctx = _ctx()
    _ = ToolRegistry([make_tool("spy", "Records ctx.", _EchoInput, spy)]).call("spy", ctx, {"n": 1})

    assert seen == [ctx] and seen[0] is ctx
