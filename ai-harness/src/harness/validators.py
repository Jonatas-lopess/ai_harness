"""Fundamentação de números: todo número do texto gerado precisa vir de um resultado de tool ou de um fato.

O algoritmo é do harness; **o que conta como "valor" é do pack** (`TokenReader`): formato de milhar e decimal,
siglas, datas e números de processo mudam por domínio. O harness não tem leitor padrão de propósito.

O valor de um token é qualquer coisa `Hashable` comparada por igualdade: `Decimal` para números, `date` para datas, `str`
normalizada para identificadores com zeros à esquerda (número de processo). Tipos diferentes nunca se igualam
(`date(2026, 3, 15) != Decimal(20260315)`), então uma quantidade não fundamenta uma data. Duas `str` de naturezas
diferentes (uma data e um id que escrevam a mesma coisa) se igualam: se isso importar, o leitor etiqueta o valor.
"""

import re
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast

from pydantic import BaseModel

from harness.agent import ToolCallRecord


@dataclass(frozen=True)
class Token:
    text: str  # como aparece no texto
    start: int
    end: int
    values: frozenset[Hashable]  # o que o texto pode significar; vazio = não sei ler (nunca fundamentado)


class TokenReader(Protocol):
    def find(self, text: str) -> Sequence[Token]: ...


def _collect(value: object, out: set[Hashable], reader: TokenReader) -> None:
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


def _numbers_of(sources: Iterable[BaseModel], reader: TokenReader) -> set[Hashable]:
    allowed: set[Hashable] = set()
    for source in sources:
        _collect(source.model_dump(mode="json"), allowed, reader)
    return allowed


def grounded_values(records: Sequence[ToolCallRecord], reader: TokenReader) -> set[Hashable]:
    return _numbers_of((record.result for record in records), reader)


def ungrounded_tokens(text: str, records: Sequence[ToolCallRecord], reader: TokenReader) -> list[str]:
    """Números do texto sem origem nos resultados das tools, como escritos. Lista vazia = aprovado.

    Número ambíguo passa se alguma leitura dele bater com um valor das tools.
    Não cobre cálculo derivado (somas, percentuais): quem calcula é o código, a tool devolve pronto.
    """
    return _ungrounded(text, grounded_values(records, reader), reader)


def ungrounded_in(text: str, facts: BaseModel, reader: TokenReader) -> list[str]:
    """Mesma regra, com os fatos que o job mandou no prompt como única origem."""
    return _ungrounded(text, _numbers_of([facts], reader), reader)


def _ungrounded(text: str, allowed: set[Hashable], reader: TokenReader) -> list[str]:
    return [t.text for t in reader.find(text) if not t.values & allowed]


# Fim de oração: pontuação seguida de espaço/fim. "1.250" e "1,5" não quebram (sem espaço depois).
_CLAUSE_END = re.compile(r"[.;:,!?](?=\s|$)|\n")


def mislabeled_tokens(
    text: str,
    values: Mapping[str, Hashable],
    aliases: Mapping[str, Sequence[str]],
    reader: TokenReader,
) -> list[str]:
    """Números que existem nos fatos mas estão ligados ao campo errado. Lista vazia = aprovado.

    Por oração, o rótulo (palavra de `aliases`) mais próximo ANTES do número (ou, se nenhum
    precede, o mais próximo depois) diz o campo que o texto afirma; o número tem que ser o valor
    desse campo. Só valem rótulos entre este número e o vizinho: em "faturamento de R$ 10.950 com
    465 unidades", `R$` pertence ao 10.950, não ao 465. Sem rótulo na oração, não julga: o que
    não tem origem nos fatos já é pego por `ungrounded_in`. Heurística de palavras, não de gramática.
    """
    known = set(values.values())
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
            if values[field] not in number_values:
                wrong.append(f"{match.text} (next to '{field}', which is {values[field]})")
    return wrong
