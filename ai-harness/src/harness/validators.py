"""Fundamentação de números: todo número do texto gerado precisa vir de um resultado de tool ou de um fato.

O algoritmo é do harness; **o que conta como número é do pack** (`NumberReader`): formato de milhar e
decimal, siglas, datas e números de processo mudam por domínio. O harness não tem leitor padrão de propósito.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast

from pydantic import BaseModel

from harness.agent import ToolCallRecord


@dataclass(frozen=True)
class NumberToken:
    text: str  # como aparece no texto
    start: int
    end: int
    values: frozenset[Decimal]  # valores que o texto pode representar; vazio = não sei ler (nunca fundamentado)


class NumberReader(Protocol):
    def find(self, text: str) -> Sequence[NumberToken]: ...


def _collect(value: object, out: set[Decimal], reader: NumberReader) -> None:
    """Percorre o resultado da tool: números entram pelo valor, textos pelo mesmo leitor do texto gerado."""
    if isinstance(value, bool):
        return  # bool é subclasse de int: `True` não é o número 1
    if isinstance(value, (int, float)):
        out.add(Decimal(str(value)))
    elif isinstance(value, str):
        for token in reader.find(value):
            out |= token.values
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            _collect(item, out, reader)
    elif isinstance(value, Iterable):
        for item in value:
            _collect(item, out, reader)


def _numbers_of(sources: Iterable[BaseModel], reader: NumberReader) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for source in sources:
        _collect(source.model_dump(mode="json"), allowed, reader)
    return allowed


def grounded_numbers(records: Sequence[ToolCallRecord], reader: NumberReader) -> set[Decimal]:
    return _numbers_of((record.result for record in records), reader)


def ungrounded_numbers(text: str, records: Sequence[ToolCallRecord], reader: NumberReader) -> list[str]:
    """Números do texto sem origem nos resultados das tools, como escritos. Lista vazia = aprovado.

    Número ambíguo passa se alguma leitura dele bater com um valor das tools.
    Não cobre cálculo derivado (somas, percentuais): quem calcula é o código, a tool devolve pronto.
    """
    return _ungrounded(text, grounded_numbers(records, reader), reader)


def ungrounded_in(text: str, facts: BaseModel, reader: NumberReader) -> list[str]:
    """Mesma regra, com os fatos que o job mandou no prompt como única origem."""
    return _ungrounded(text, _numbers_of([facts], reader), reader)


def _ungrounded(text: str, allowed: set[Decimal], reader: NumberReader) -> list[str]:
    return [t.text for t in reader.find(text) if not t.values & allowed]


# Fim de oração: pontuação seguida de espaço/fim. "1.250" e "1,5" não quebram (sem espaço depois).
_CLAUSE_END = re.compile(r"[.;:,!?](?=\s|$)|\n")


def mislabeled_numbers(
    text: str,
    values: Mapping[str, int | Decimal],
    aliases: Mapping[str, Sequence[str]],
    reader: NumberReader,
) -> list[str]:
    """Números que existem nos fatos mas estão ligados ao campo errado. Lista vazia = aprovado.

    Por oração, o rótulo (palavra de `aliases`) mais próximo ANTES do número (ou, se nenhum
    precede, o mais próximo depois) diz o campo que o texto afirma; o número tem que ser o valor
    desse campo. Só valem rótulos entre este número e o vizinho: em "faturamento de R$ 10.950 com
    465 unidades", `R$` pertence ao 10.950, não ao 465. Sem rótulo na oração, não julga: o que
    não tem origem nos fatos já é pego por `ungrounded_in`. Heurística de palavras, não de gramática.
    """
    known = {Decimal(v) for v in values.values()}
    wrong: list[str] = []
    for clause in _CLAUSE_END.split(text):
        marks = [
            (m.start(), m.end(), field)
            for field, words in aliases.items()
            for word in words
            for m in re.finditer(re.escape(word), clause, re.IGNORECASE)
        ]
        numbers = list(reader.find(clause))
        for i, match in enumerate(numbers):
            number_values = match.values
            if not number_values & known:
                continue
            # Um rótulo só vale para o número vizinho: busca entre este número e o anterior/seguinte.
            floor = numbers[i - 1].end if i > 0 else 0
            ceiling = numbers[i + 1].start if i + 1 < len(numbers) else len(clause)
            before = [
                (match.start - end, field)
                for start, end, field in marks
                if start >= floor and end <= match.start
            ]
            after = [
                (start - match.end, field)
                for start, end, field in marks
                if start >= match.end and end <= ceiling
            ]
            candidates = before or after  # "ponto de 105": o rótulo costuma vir antes do número
            if not candidates:
                continue
            _, field = min(candidates)
            if Decimal(values[field]) not in number_values:
                wrong.append(f"{match.text} (next to '{field}', which is {values[field]})")
    return wrong
