"""Digest de prazos: o código decide o que entra, a ordem, a data e a `source_ref`; o LLM só escreve uma frase por item.

Um item = uma linha do registro = uma chamada `narrate` com os fatos só daquela linha. Assim a data da frase só pode
ser a daquela linha (`ungrounded_in` já garante), e a ligação frase-ref é estrutural: o modelo nunca escreve ref.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from harness.llm import LLMClient, Usage, add_usage
from harness.narrate import narrate
from harness.pricing import costed_span
from harness.tools import ToolError
from pydantic import BaseModel

from legal_context import LegalContext
from legal_prices import load_legal_prices
from legal_tokens import LEGAL_TOKENS
from legal_tools import DeadlineItem, UpcomingDeadlinesOutput, legal_registry

type Situation = Literal["overdue", "upcoming"]

PROMPT_VERSION = "deadline-sentence-v2"

SYSTEM_PROMPT = (
    "Você escreve uma frase para o digest diário de um advogado, sobre um único prazo. Receberá os fatos "
    "do prazo em JSON. Escreva UMA frase em português com o tipo do prazo (use as palavras de `kind`) e a data de vencimento no formato "
    "dd/mm/aaaa, e o número do processo. Se `situation` for `overdue`, diga que o prazo já venceu e continua "
    "aberto. Use somente o que está nos fatos, exatamente como está. Não calcule, não conte dias, não "
    "estime, não interprete nem dê conselho, e não mencione dado que não esteja nos fatos."
)

class DeadlineFacts(BaseModel):
    """Tudo que o modelo pode citar sobre UM prazo. Sem `source_ref` nem ids: um id seria um inteiro "fundamentado"."""

    kind: str
    due_date: date
    case_number: str
    situation: Situation


@dataclass(frozen=True)
class DigestItem:
    """Os campos de registro vêm do código; só `sentence` vem do modelo, e só se passou na validação."""

    source_ref: str
    situation: Situation
    kind: str
    due_date: str
    case_number: str
    sentence: str | None
    warning: str | None  # preenchido quando a frase falhou: o item sai só com os dados do registro
    attempts: int  # chamadas ao modelo para este item; 1 = aceita de primeira (o que o eval real mede)


@dataclass(frozen=True)
class Digest:
    items: list[DigestItem]
    usage: Usage
    prompt_version: str
    model: str


def _facts(item: DeadlineItem, situation: Situation) -> DeadlineFacts:
    return DeadlineFacts(
        kind=item.kind,
        due_date=date.fromisoformat(item.due_date),
        case_number=item.case_number,
        situation=situation,
    )


def build_digest(
    client: LLMClient, deadlines: UpcomingDeadlinesOutput, *, model: str, max_attempts: int = 3
) -> Digest:
    """Vencidos primeiro. Frase reprovada não derruba o digest: o item sai com os dados do registro e um aviso."""
    overdue: list[tuple[DeadlineItem, Situation]] = [(i, "overdue") for i in deadlines.overdue]
    upcoming: list[tuple[DeadlineItem, Situation]] = [(i, "upcoming") for i in deadlines.upcoming]
    rows = overdue + upcoming
    total = Usage(0, 0)
    items: list[DigestItem] = []
    for row, situation in rows:
        facts = _facts(row, situation)
        explanation = narrate(
            client,
            facts,
            system=SYSTEM_PROMPT,
            values={},  # rótulo trocado (`mislabeled_tokens`) não se aplica: uma data só por linha, nada a trocar
            aliases={},
            reader=LEGAL_TOKENS,
            model=model,
            max_attempts=max_attempts,
            required=[facts.kind],  # o tipo do prazo é palavra, não número: só esta checagem o confere
        )
        total = add_usage(total, explanation.usage)
        items.append(
            DigestItem(
                source_ref=row.source_ref,
                situation=situation,
                kind=row.kind,
                due_date=row.due_date,
                case_number=row.case_number,
                sentence=explanation.rationale,
                warning=None if explanation.rationale else f"frase não validada: {explanation.error}",
                attempts=explanation.attempts,
            )
        )
    return Digest(items, total, PROMPT_VERSION, model)


def run_digest_job(
    client: LLMClient, ctx: LegalContext, *, model: str, days: int = 30, max_attempts: int = 3
) -> Digest:
    with costed_span("digest_job", prices=load_legal_prices(), model=model, prompt_version=PROMPT_VERSION):
        result = legal_registry().call("upcoming_deadlines", ctx, {"days": days})
        if isinstance(result, ToolError):
            raise RuntimeError(f"upcoming_deadlines failed: {result.error}")
        assert isinstance(result, UpcomingDeadlinesOutput)
        return build_digest(client, result, model=model, max_attempts=max_attempts)
