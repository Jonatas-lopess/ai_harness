"""Job de reposição: o código detecta e calcula, o LLM só escreve a justificativa de cada item."""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar

import psycopg
from pydantic import BaseModel, ConfigDict

from extract import (
    ExtractionError,
    InvalidOutputError,
    LLMClient,
    RefusedError,
    TruncatedOutputError,
    Usage,
    add_usage,
    parse_completion,
    with_feedback,
)
from replenishment import DEFAULT_COVER_DAYS, DEFAULT_WINDOW_DAYS, low_stock
from validators import mislabeled_numbers, ungrounded_in

PROMPT_VERSION = "refill-rationale-v1"
MAX_COMPLETION_TOKENS = 256

SYSTEM_PROMPT = (
    "Você escreve a justificativa de uma sugestão de reposição de estoque para a equipe de compras. "
    "Receberá os fatos do produto em JSON. Escreva 1 ou 2 frases em português explicando por que "
    "repor, citando somente números que estão nos fatos. Não calcule, não some, não estime prazos, "
    "datas nem valores, e não mencione nenhum dado que não esteja nos fatos."
)


class RefillFacts(BaseModel):
    """Tudo que o modelo pode citar. Vem do código; número fora daqui reprova o texto."""

    product_id: int
    name: str
    on_hand: int
    open_po_qty: int
    reorder_point: int
    suggested_qty: int

    def labelled_values(self) -> dict[str, int]:
        return {
            "on_hand": self.on_hand,
            "reorder_point": self.reorder_point,
            "open_po_qty": self.open_po_qty,
            "suggested_qty": self.suggested_qty,
        }


# Palavras que ligam um número a um campo dos fatos (ver `mislabeled_numbers`).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "on_hand": ("estoque", "disponível", "disponivel", "em mãos", "on_hand"),
    "reorder_point": ("ponto", "reorder_point"),
    "open_po_qty": ("pedido", "a caminho", "em trânsito", "open_po_qty"),
    "suggested_qty": ("repor", "comprar", "sugerid", "suggested_qty"),
}


class Rationale(BaseModel):
    """O que o MODELO preenche: só texto. Sem `suggested_qty` no schema, ele não tem onde escrever."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    rationale: str


class RefillSuggestion(RefillFacts):
    # None = o texto do modelo falhou ou foi reprovado; a quantidade (do código) continua valendo.
    rationale: str | None
    rationale_error: str | None


@dataclass(frozen=True)
class RefillReport:
    items: tuple[RefillSuggestion, ...]
    usage: Usage
    prompt_version: str
    model: str


@dataclass(frozen=True)
class Explanation:
    rationale: str | None
    error: str | None
    usage: Usage
    attempts: int


def explain(
    client: LLMClient, facts: RefillFacts, *, model: str, max_attempts: int = 3
) -> Explanation:
    """Pede a justificativa de um item. Texto com número fora dos fatos volta ao modelo com o erro."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    base = facts.model_dump_json()
    user = base
    total = Usage(0, 0)
    last_error: InvalidOutputError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            completion = client.complete(
                model=model,
                system=SYSTEM_PROMPT,
                user=user,
                response_schema=Rationale.model_json_schema(),
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
            total = add_usage(total, completion.usage)
            text = parse_completion(completion, Rationale).rationale
            if not text.strip():
                raise InvalidOutputError("empty rationale", completion.usage)
            stray = ungrounded_in(text, facts)
            if stray:
                raise InvalidOutputError(f"numbers not present in the facts: {stray}", completion.usage)
            swapped = mislabeled_numbers(text, facts.labelled_values(), FIELD_ALIASES)
            if swapped:
                raise InvalidOutputError(
                    f"numbers attached to the wrong field: {swapped}", completion.usage
                )
        except InvalidOutputError as exc:
            last_error = exc
            user = with_feedback(base, exc)
            continue
        except (TruncatedOutputError, RefusedError) as exc:
            # Problema deste item e retry repetiria igual: degrada o item, o resto do job segue.
            return Explanation(None, str(exc), total, attempt)
        except ExtractionError as exc:
            # Provedor fora do ar não é problema do item: sobe, com o uso acumulado.
            exc.usage = total
            raise
        return Explanation(text, None, total, attempt)

    return Explanation(
        None, f"rationale rejected after {max_attempts} attempts: {last_error}", total, max_attempts
    )


def run_refill_job(
    client: LLMClient,
    conn: psycopg.Connection,
    as_of: date,
    *,
    model: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cover_days: int = DEFAULT_COVER_DAYS,
    max_attempts: int = 3,
) -> RefillReport:
    flagged = low_stock(conn, as_of, window_days, cover_days)
    # Prioridade decidida pelo código: maior quantidade sugerida primeiro.
    flagged.sort(key=lambda p: (-p.suggested_qty, p.product_id))

    total = Usage(0, 0)
    items: list[RefillSuggestion] = []
    for position in flagged:
        facts = RefillFacts(
            product_id=position.product_id,
            name=position.name,
            on_hand=position.on_hand,
            open_po_qty=position.open_po_qty,
            reorder_point=position.reorder_point,
            suggested_qty=position.suggested_qty,
        )
        try:
            explanation = explain(client, facts, model=model, max_attempts=max_attempts)
        except ExtractionError as exc:
            exc.usage = add_usage(total, exc.usage)
            raise
        total = add_usage(total, explanation.usage)
        items.append(
            RefillSuggestion(
                product_id=facts.product_id,
                name=facts.name,
                on_hand=facts.on_hand,
                open_po_qty=facts.open_po_qty,
                reorder_point=facts.reorder_point,
                suggested_qty=facts.suggested_qty,
                rationale=explanation.rationale,
                rationale_error=explanation.error,
            )
        )
    return RefillReport(tuple(items), total, PROMPT_VERSION, model)
