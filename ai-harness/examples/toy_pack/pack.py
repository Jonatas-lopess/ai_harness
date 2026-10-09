"""Pack de brinquedo: um helpdesk mínimo (tickets abertos por fila), SEM nada de ERP.

É o exemplo de "como escrever um pack" (leia de cima para baixo) e a prova do critério da fase 5: um domínio novo
usa o harness só por `harness.*`, sem editá-lo. Tudo aqui é o que um pack real teria que fornecer: contexto, tools,
leitor de números, prompt, preços e suítes. O teste está em `tests/test_toy_pack.py`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from harness.agent import ChatClient
from harness.answers import STATUS_PROTOCOL, QuestionResult, answer_question
from harness.evals import Scored, Suite
from harness.llm import LLMClient
from harness.narrate import Explanation, narrate
from harness.pricing import Price, PriceTable, costed_span
from harness.tools import Tool, ToolError, ToolInput, ToolRegistry, make_tool
from harness.validators import Token

MODEL = "toy-model"


# --- contexto: o que o pack injeta nas tools (aqui, uma lista em memória; no ERP seria uma conexão) ------------------


@dataclass(frozen=True)
class Ticket:
    queue: str
    opened: date


@dataclass(frozen=True)
class HelpdeskContext:
    tickets: tuple[Ticket, ...]
    today: date  # data de negócio injetada: o modelo nunca a escolhe


# --- tools --------------------------------------------------------------------------------------------------------


class QueueInput(ToolInput):
    queue: str


class QueueStats(BaseModel):
    queue: str
    open_tickets: int
    oldest_days: int


def _queue_stats(ctx: HelpdeskContext, args: QueueInput) -> BaseModel:
    mine = [t for t in ctx.tickets if t.queue == args.queue]
    if not mine:
        return ToolError(error=f"unknown queue '{args.queue}'")
    return QueueStats(
        queue=args.queue, open_tickets=len(mine), oldest_days=max((ctx.today - t.opened).days for t in mine)
    )


def toy_tools() -> list[Tool[HelpdeskContext]]:
    return [make_tool("queue_stats", "Open tickets and age of the oldest one in a queue.", QueueInput, _queue_stats)]


def toy_registry() -> ToolRegistry[HelpdeskContext]:
    return ToolRegistry(toy_tools())


# --- o que conta como número neste domínio (inteiros soltos; "TK-7" é identificador) ---------------------------------


class ToyNumbers:
    def find(self, text: str) -> Sequence[Token]:
        return [
            Token(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())}))
            for m in re.finditer(r"(?<![\w-])\d+(?![\w-])", text)
        ]


TOY_NUMBERS = ToyNumbers()


# --- prompt e preços ---------------------------------------------------------------------------------------------

ASK_PROMPT = "Você ajuda a equipe de suporte. Use as tools para obter fatos; nunca invente números. " + STATUS_PROTOCOL
NARRATE_PROMPT = "Escreva uma frase sobre a fila com os fatos recebidos. Use somente os números dos fatos."

PRICES = PriceTable(
    source="toy",
    effective_date="2026-10-01",
    currency="USD",
    models={MODEL: Price(input_per_mtok=Decimal("1"), output_per_mtok=Decimal("2"))},
)

ALIASES = {"open_tickets": ("tickets", "abertos"), "oldest_days": ("dias",)}


# --- o job: uma função do pack que compõe as peças do harness ---------------------------------------------------------


@dataclass(frozen=True)
class QueueReport:
    answer: QuestionResult
    summary: Explanation


def queue_job(
    chat: ChatClient, client: LLMClient, ctx: HelpdeskContext, queue: str, *, prices: PriceTable | None = PRICES
) -> QueueReport:
    with costed_span("queue_job", prices=prices, model=MODEL):
        answer = answer_question(
            chat,
            toy_registry(),
            ctx,
            f"Como está a fila {queue}?",
            system=ASK_PROMPT,
            reader=TOY_NUMBERS,
            model=MODEL,
            max_steps=4,
        )
        facts = QueueStats(queue=queue, open_tickets=0, oldest_days=0)
        for call in answer.agent.tool_calls:
            if isinstance(call.result, QueueStats):
                facts = call.result
        summary = narrate(
            client,
            facts,
            system=NARRATE_PROMPT,
            values={"open_tickets": facts.open_tickets, "oldest_days": facts.oldest_days},
            aliases=ALIASES,
            reader=TOY_NUMBERS,
            model=MODEL,
        )
        return QueueReport(answer, summary)


# --- suíte de evals do pack ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Case:
    name: str


@dataclass(frozen=True)
class _Result:
    case: _Case
    passed: bool


def toy_suite() -> Sequence[Scored]:
    ctx = HelpdeskContext((Ticket("billing", date(2026, 10, 1)),), date(2026, 10, 4))
    stats = _queue_stats(ctx, QueueInput(queue="billing"))
    return [_Result(_Case("billing-has-one-open-ticket-aged-3-days"), stats == QueueStats(queue="billing", open_tickets=1, oldest_days=3))]


TOY_SUITES: dict[str, Suite] = {"toy": toy_suite}
