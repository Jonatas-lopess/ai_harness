"""Laço genérico "fatos -> texto validado": o job decide os fatos, o LLM só escreve o texto.

Serve a qualquer job que narre fatos (reposição, fechamento): o que muda entre eles é o prompt,
os fatos e os rótulos. Candidato a ir para o harness na fase 5.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

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
from validators import mislabeled_numbers, ungrounded_in

MAX_COMPLETION_TOKENS = 256


class Rationale(BaseModel):
    """O que o MODELO preenche: só texto. Sem `suggested_qty` no schema, ele não tem onde escrever."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    rationale: str



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
    values: Mapping[str, int | Decimal],
    aliases: Mapping[str, Sequence[str]],
    model: str,
    max_attempts: int = 3,
) -> Explanation:
    """Pede o texto sobre `facts`. Número sem origem ou no campo errado volta ao modelo com o erro."""
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
                system=system,
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
            swapped = mislabeled_numbers(text, values, aliases)
            if swapped:
                raise InvalidOutputError(
                    f"numbers attached to the wrong field: {swapped}", completion.usage
                )
        except InvalidOutputError as exc:
            last_error = exc
            user = with_feedback(base, exc)
            continue
        except (TruncatedOutputError, RefusedError) as exc:
            # Problema deste texto e retry repetiria igual: degrada, o resto do job segue.
            return Explanation(None, str(exc), total, attempt)
        except ExtractionError as exc:
            # Provedor fora do ar não é problema do texto: sobe, com o uso acumulado.
            exc.usage = total
            raise
        return Explanation(text, None, total, attempt)

    return Explanation(
        None, f"rationale rejected after {max_attempts} attempts: {last_error}", total, max_attempts
    )
