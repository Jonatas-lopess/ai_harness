"""Laço genérico "fatos -> texto validado": o job decide os fatos, o LLM só escreve o texto.

Serve a qualquer job que narre fatos (reposição, fechamento, andamentos): o que muda entre eles é o prompt,
os fatos, os rótulos e o leitor de números (`TokenReader`), todos vindos do pack.
"""

import unicodedata
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from harness.llm import (
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
from pydantic import BaseModel, ConfigDict

from harness.pricing import usage_attributes
from harness.tracing import span
from harness.validators import TokenReader, mislabeled_tokens, ungrounded_in

MAX_COMPLETION_TOKENS = 256


class Rationale(BaseModel):
    """O que o MODELO preenche: só texto. Sem `suggested_qty` no schema, ele não tem onde escrever."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    rationale: str



def _fold(text: str) -> str:
    """Sem caixa e sem acento: "Contestação" e "contestacao" são o mesmo termo."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def missing_terms(text: str, required: Sequence[str]) -> list[str]:
    """Termos de `required` que o texto não menciona. Lista vazia = aprovado."""
    folded = _fold(text)
    return [term for term in required if _fold(term) not in folded]


@dataclass(frozen=True)
class Explanation:
    rationale: str | None
    error: str | None
    usage: Usage
    attempts: int


def narrate(
    client: LLMClient,
    facts: BaseModel,
    *,
    system: str,
    values: Mapping[str, Hashable],
    aliases: Mapping[str, Sequence[str]],
    reader: TokenReader,
    model: str,
    max_attempts: int = 3,
    required: Sequence[str] = (),
) -> Explanation:
    """Pede o texto sobre `facts`. Número sem origem ou no campo errado volta ao modelo com o erro.

    `required`: termos que o texto precisa mencionar (ex.: o tipo do prazo). Os validadores de número não leem
    palavras, então um rótulo trocado ("recurso" no lugar de "contestação") só é pego aqui. Vazio = não confere.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    base = facts.model_dump_json()
    user = base
    total = Usage(0, 0)
    last_error: InvalidOutputError | None = None
    # Fatos entram uma vez, aqui; cada tentativa guarda só o que o modelo devolveu e por que foi (ou não) aceito.
    with span("narrate", facts=base, system=system, model=model, max_attempts=max_attempts) as run_span:
        for attempt in range(1, max_attempts + 1):
            try:
                with span("llm_call", attempt=attempt, model=model, retry_feedback=user != base) as call_span:
                    completion = client.complete(
                        model=model,
                        system=system,
                        user=user,
                        response_schema=Rationale.model_json_schema(),
                        max_completion_tokens=MAX_COMPLETION_TOKENS,
                    )
                    usage = completion.usage
                    call_span.set(
                        **usage_attributes(usage, model),
                        finish_reason=completion.finish_reason,
                        content=completion.content,
                    )
                    if user != base:
                        # Retentativa: o texto enviado (fatos + motivo da rejeição) é a causa direta do texto novo.
                        # Na primeira tentativa o `user` são os fatos, que já estão no span `narrate`.
                        call_span.set(user=user)
                total = add_usage(total, completion.usage)
                # Chamada ok e texto rejeitado são coisas diferentes: a rejeição fica no span `validate`.
                with span("validate", attempt=attempt):
                    text = parse_completion(completion, Rationale).rationale
                    if not text.strip():
                        raise InvalidOutputError("empty rationale", completion.usage)
                    stray = ungrounded_in(text, facts, reader)
                    if stray:
                        raise InvalidOutputError(f"numbers not present in the facts: {stray}", completion.usage)
                    swapped = mislabeled_tokens(text, values, aliases, reader)
                    if swapped:
                        raise InvalidOutputError(
                            f"numbers attached to the wrong field: {swapped}", completion.usage
                        )
                    absent = missing_terms(text, required)
                    if absent:
                        raise InvalidOutputError(f"required terms missing from the text: {absent}", completion.usage)
            except InvalidOutputError as exc:
                last_error = exc
                user = with_feedback(base, exc)
                continue
            except (TruncatedOutputError, RefusedError) as exc:
                # Problema deste texto e retry repetiria igual: degrada, o resto do job segue.
                run_span.set(attempts=attempt, outcome="degraded", error=str(exc))
                return Explanation(None, str(exc), total, attempt)
            except ExtractionError as exc:
                # Provedor fora do ar não é problema do texto: sobe, com o uso acumulado.
                exc.usage = total
                raise
            run_span.set(attempts=attempt, outcome="accepted")
            return Explanation(text, None, total, attempt)

        run_span.set(attempts=max_attempts, outcome="rejected")
        return Explanation(
            None, f"rationale rejected after {max_attempts} attempts: {last_error}", total, max_attempts
        )
