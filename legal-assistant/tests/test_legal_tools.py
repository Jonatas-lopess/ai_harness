from datetime import date

import psycopg
from harness.tools import ToolError, ToolRegistry
from pydantic import BaseModel
from pytest import fixture, mark, raises

from legal_context import LegalContext, connect_readonly
from legal_tools import UpcomingDeadlinesOutput, deadline_ref, legal_registry
from settings import get_settings

AS_OF = date(2026, 3, 10)


@fixture
def registry() -> ToolRegistry[LegalContext]:
    return legal_registry()


@fixture
def ctx():
    with connect_readonly(get_settings().database_url.get_secret_value()) as conn:
        yield LegalContext(conn=conn, as_of=AS_OF, user_id="ana")


def _refs(output: BaseModel) -> tuple[list[str], list[str]]:
    assert isinstance(output, UpcomingDeadlinesOutput)
    return [i.source_ref for i in output.overdue], [i.source_ref for i in output.upcoming]


def test_the_model_cannot_choose_the_user(registry: ToolRegistry[LegalContext]) -> None:
    (schema,) = registry.schemas()

    assert set(schema["parameters"]["properties"]) == {"days"}  # pyright: ignore[reportIndexIssue, reportArgumentType]


def test_the_context_has_no_default_user() -> None:
    with raises(TypeError, match="user_id"):
        _ = LegalContext(conn=None, as_of=AS_OF)  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_the_ref_is_built_by_code_from_the_row_id() -> None:
    assert deadline_ref(17) == "deadline:17"


@mark.integration
def test_ana_sees_overdue_and_upcoming_apart(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    result = registry.call("upcoming_deadlines", ctx, {"days": 30})

    # Seed: 3 vencido (processo 2); 1, 4, 2 por data; 6 está `done` e 5 é do bruno.
    assert _refs(result) == (["deadline:3"], ["deadline:1", "deadline:4", "deadline:2"])


@mark.integration
def test_dates_are_the_ones_in_the_record(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    result = registry.call("upcoming_deadlines", ctx, {"days": 30})

    assert isinstance(result, UpcomingDeadlinesOutput)
    assert [(i.due_date, i.kind, i.case_number) for i in result.upcoming][0] == (
        "2026-03-13",
        "contestação",
        "0001234-56.2024.8.26.0100",
    )


@mark.integration
def test_the_window_includes_its_last_day(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    # as_of + 3 dias = 2026-03-13, o dia do prazo 1.
    assert _refs(registry.call("upcoming_deadlines", ctx, {"days": 3})) == (["deadline:3"], ["deadline:1"])
    assert _refs(registry.call("upcoming_deadlines", ctx, {"days": 2})) == (["deadline:3"], [])


@mark.integration
def test_the_deadline_due_today_is_upcoming_not_overdue(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    today = LegalContext(conn=ctx.conn, as_of=date(2026, 3, 13), user_id="ana")

    overdue, upcoming = _refs(registry.call("upcoming_deadlines", today, {"days": 1}))

    assert "deadline:1" in upcoming and "deadline:1" not in overdue


@mark.integration
def test_each_user_sees_only_their_matters(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    bruno = LegalContext(conn=ctx.conn, as_of=AS_OF, user_id="bruno")

    assert _refs(registry.call("upcoming_deadlines", bruno, {"days": 30})) == ([], ["deadline:5"])
    assert "deadline:5" not in sum(_refs(registry.call("upcoming_deadlines", ctx, {"days": 90})), [])


@mark.integration
def test_unknown_user_sees_nothing(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    nobody = LegalContext(conn=ctx.conn, as_of=AS_OF, user_id="carla")

    assert _refs(registry.call("upcoming_deadlines", nobody, {"days": 90})) == ([], [])


@mark.integration
def test_a_user_argument_from_the_model_is_rejected(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    result = registry.call("upcoming_deadlines", ctx, {"days": 30, "responsible_user": "bruno"})

    assert isinstance(result, ToolError)
    assert "responsible_user" in result.error


@mark.integration
def test_days_out_of_range_is_rejected(registry: ToolRegistry[LegalContext], ctx: LegalContext) -> None:
    for days in (0, 91):
        result = registry.call("upcoming_deadlines", ctx, {"days": days})
        assert isinstance(result, ToolError) and "days" in result.error


@mark.integration
def test_the_connection_is_read_only(ctx: LegalContext) -> None:
    with raises(psycopg.errors.ReadOnlySqlTransaction):
        _ = ctx.conn.execute("DELETE FROM deadlines")
