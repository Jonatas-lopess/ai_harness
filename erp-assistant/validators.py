"""Validador de números: todo número do texto gerado precisa vir de um resultado de tool."""

import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import cast

from pydantic import BaseModel

from agent import ToolCallRecord

# Número isolado: dígito colado em letra/underscore/dígito é identificador ("A12", "B07"), não número.
# Separadores só entram se seguidos de dígito, então o ponto final de uma frase fica de fora.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)*(?![A-Za-z0-9_])")
_SEPARATOR = re.compile(r"[.,]")


def _values(token: str) -> set[Decimal]:
    """Valores que o texto do número pode representar. "1.250" é 1250 (pt-BR) ou 1,25 (en): ambíguo."""
    seps = _SEPARATOR.findall(token)
    if not seps:
        return {Decimal(token)}
    parts = _SEPARATOR.split(token)
    values: set[Decimal] = set()
    # Todos os separadores são de milhar: mesmo caractere e grupos de 3 dígitos.
    if len(set(seps)) == 1 and all(len(p) == 3 for p in parts[1:]):
        values.add(Decimal("".join(parts)))
    # O último separador é a vírgula decimal; os anteriores, se houver, são de milhar.
    head, fraction = parts[:-1], parts[-1]
    head_seps = seps[:-1]
    if (
        len(set(head_seps)) <= 1
        and seps[-1] not in head_seps
        and all(len(p) == 3 for p in head[1:])
    ):
        values.add(Decimal("".join(head) + "." + fraction))
    return values


def _numbers_in(text: str) -> list[tuple[str, set[Decimal]]]:
    return [(m.group(), _values(m.group())) for m in _NUMBER.finditer(text)]


def _collect(value: object, out: set[Decimal]) -> None:
    """Percorre o resultado da tool: números entram pelo valor, textos pelo mesmo extrator do texto."""
    if isinstance(value, bool):
        return  # bool é subclasse de int: `True` não é o número 1
    if isinstance(value, (int, float)):
        out.add(Decimal(str(value)))
    elif isinstance(value, str):
        for _, values in _numbers_in(value):
            out |= values
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            _collect(item, out)
    elif isinstance(value, Iterable):
        for item in value:
            _collect(item, out)


def _numbers_of(sources: Iterable[BaseModel]) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for source in sources:
        _collect(source.model_dump(mode="json"), allowed)
    return allowed


def grounded_numbers(records: Sequence[ToolCallRecord]) -> set[Decimal]:
    return _numbers_of(record.result for record in records)


def ungrounded_numbers(text: str, records: Sequence[ToolCallRecord]) -> list[str]:
    """Números do texto sem origem nos resultados das tools, como escritos. Lista vazia = aprovado.

    Número ambíguo ("1.250") passa se alguma leitura dele bater com um valor das tools.
    Não cobre cálculo derivado (somas, percentuais): quem calcula é o código, a tool devolve pronto.
    """
    return _ungrounded(text, grounded_numbers(records))


def ungrounded_in(text: str, facts: BaseModel) -> list[str]:
    """Mesma regra, com os fatos que o job mandou no prompt como única origem."""
    return _ungrounded(text, _numbers_of([facts]))


def _ungrounded(text: str, allowed: set[Decimal]) -> list[str]:
    return [token for token, values in _numbers_in(text) if not values & allowed]


# Fim de oração: pontuação seguida de espaço/fim. "1.250" e "1,5" não quebram (sem espaço depois).
_CLAUSE_END = re.compile(r"[.;:,!?](?=\s|$)|\n")


def mislabeled_numbers(
    text: str, values: Mapping[str, int | Decimal], aliases: Mapping[str, Sequence[str]]
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
        numbers = list(_NUMBER.finditer(clause))
        for i, match in enumerate(numbers):
            number_values = _values(match.group())
            if not number_values & known:
                continue
            # Um rótulo só vale para o número vizinho: busca entre este número e o anterior/seguinte.
            floor = numbers[i - 1].end() if i > 0 else 0
            ceiling = numbers[i + 1].start() if i + 1 < len(numbers) else len(clause)
            before = [
                (match.start() - end, field)
                for start, end, field in marks
                if start >= floor and end <= match.start()
            ]
            after = [
                (start - match.end(), field)
                for start, end, field in marks
                if start >= match.end() and end <= ceiling
            ]
            candidates = before or after  # "ponto de 105": o rótulo costuma vir antes do número
            if not candidates:
                continue
            _, field = min(candidates)
            if Decimal(values[field]) not in number_values:
                wrong.append(f"{match.group()} (next to '{field}', which is {values[field]})")
    return wrong
