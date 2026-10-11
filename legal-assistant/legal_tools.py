"""Tools do pack Legal: somente leitura. Toda data vem do registro; o `source_ref` é montado pelo código."""

from dataclasses import dataclass
from datetime import date, timedelta

from harness.tools import Tool, ToolInput, ToolRegistry, make_tool
from psycopg.rows import class_row
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


@dataclass(frozen=True)
class _DeadlineRow:
    id: int
    matter_id: int
    case_number: str
    kind: str
    due_date: date


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
    with ctx.conn.cursor(row_factory=class_row(_DeadlineRow)) as cur:
        rows = cur.execute(_DEADLINES_UP_TO, (ctx.user_id, horizon)).fetchall()
    # Prazo vencido e ainda aberto nunca some: a tool o devolve sempre, em lista própria.
    return UpcomingDeadlinesOutput(
        overdue=[_item(r) for r in rows if r.due_date < ctx.as_of],
        upcoming=[_item(r) for r in rows if r.due_date >= ctx.as_of],
    )


def _item(row: _DeadlineRow) -> DeadlineItem:
    return DeadlineItem(
        source_ref=deadline_ref(row.id),
        matter_id=row.matter_id,
        case_number=row.case_number,
        kind=row.kind,
        due_date=row.due_date.isoformat(),
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
