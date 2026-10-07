"""Job de fechamento: o código soma o dia, o LLM só escreve o resumo."""

from dataclasses import dataclass
from datetime import date

import psycopg

from closing import ClosingFacts, closing_facts
from extract import LLMClient, Usage
from narrate import Explanation, narrate

PROMPT_VERSION = "closing-summary-v1"

SYSTEM_PROMPT = (
    "Você escreve o resumo de fechamento do dia para a equipe financeira. Receberá os fatos do dia "
    "em JSON. Escreva 1 ou 2 frases em português com o faturamento e as unidades vendidas, e cite "
    "o produto de maior faturamento. Use somente números que estão nos fatos, exatamente como "
    "estão. Não calcule, não some, não compare com outros dias, não projete nem estime nada, e não "
    "mencione dado que não esteja nos fatos."
)

# Palavras que ligam um número a um campo dos fatos (ver `mislabeled_numbers`).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("faturamento", "faturou", "receita", "total", "R$", "revenue"),
    "units": ("unidades", "itens", "units"),
}


@dataclass(frozen=True)
class ClosingReport:
    facts: ClosingFacts | None  # None = dia sem venda: não há o que resumir
    summary: str | None  # None = sem fatos, ou o texto do modelo falhou/foi reprovado
    error: str | None
    usage: Usage
    prompt_version: str
    model: str


def narrate_closing(
    client: LLMClient, facts: ClosingFacts, *, model: str, max_attempts: int = 3
) -> Explanation:
    return narrate(
        client,
        facts,
        system=SYSTEM_PROMPT,
        values=facts.labelled_values(),
        aliases=FIELD_ALIASES,
        model=model,
        max_attempts=max_attempts,
    )


def run_closing_job(
    client: LLMClient, conn: psycopg.Connection, day: date, *, model: str, max_attempts: int = 3
) -> ClosingReport:
    facts = closing_facts(conn, day)
    if facts is None:
        return ClosingReport(None, None, None, Usage(0, 0), PROMPT_VERSION, model)
    explanation = narrate_closing(client, facts, model=model, max_attempts=max_attempts)
    return ClosingReport(
        facts, explanation.rationale, explanation.error, explanation.usage, PROMPT_VERSION, model
    )
