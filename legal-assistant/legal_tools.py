"""Tools do pack Legal: somente leitura. Toda data vem do registro; o `source_ref` é montado pelo código."""

from datetime import timedelta

from harness.tools import Tool, ToolInput, ToolRegistry, make_tool
from pydantic import BaseModel, Field

from legal_context import LegalContext

MAX_DAYS = 90


def deadline_ref(deadline_id: int) -> str:
    return f"deadline:{deadline_id}"


# upcoming_deadlines ------------------------------------------------------------------------


class UpcomingDeadlinesInput(ToolInput):
    # Sem usuário aqui: quem pergunta vem de `LegalContext.user_id`, nunca do modelo.
    days: int = Field(
        default=30,
        ge=1,
        le=MAX_DAYS,
        description=f"Look-ahead window in days from today (1 to {MAX_DAYS}).",
    )


class DeadlineItem(BaseModel):
    source_ref: str
    matter_id: int
    case_number: str
    kind: str
    due_date: str  # ISO, como está no registro


class UpcomingDeadlinesOutput(BaseModel):
    overdue: list[DeadlineItem]
    upcoming: list[DeadlineItem]


_DEADLINES_UP_TO = """
    SELECT d.id, d.matter_id, m.case_number, d.kind, d.due_date
    FROM deadlines d
    JOIN matters m ON m.id = d.matter_id
    WHERE d.status = 'open'
      AND m.responsible_user = %s
      AND d.due_date <= %s
    ORDER BY d.due_date, d.id
"""


def _upcoming_deadlines(ctx: LegalContext, args: UpcomingDeadlinesInput) -> BaseModel:
    horizon = ctx.as_of + timedelta(days=args.days)
    rows = ctx.conn.execute(_DEADLINES_UP_TO, (ctx.user_id, horizon)).fetchall()
    items = [
        (
            due_date,
            DeadlineItem(
                source_ref=deadline_ref(deadline_id),
                matter_id=matter_id,
                case_number=case_number,
                kind=kind,
                due_date=due_date.isoformat(),
            ),
        )
        for deadline_id, matter_id, case_number, kind, due_date in rows
    ]
    # Prazo vencido e ainda aberto nunca some: a tool o devolve sempre, em lista própria.
    return UpcomingDeadlinesOutput(
        overdue=[item for due, item in items if due < ctx.as_of],
        upcoming=[item for due, item in items if due >= ctx.as_of],
    )


# registry ----------------------------------------------------------------------------------


def legal_tools() -> list[Tool[LegalContext]]:
    return [
        make_tool(
            "upcoming_deadlines",
            "Open deadlines of the matters of the current user: `overdue` (already past, still open;"
            + " always returned) and `upcoming` (from today up to N days ahead). Dates are exactly"
            + " as in the system of record; each item has its `source_ref`.",
            UpcomingDeadlinesInput,
            _upcoming_deadlines,
        ),
    ]


def legal_registry() -> ToolRegistry[LegalContext]:
    return ToolRegistry(legal_tools())
