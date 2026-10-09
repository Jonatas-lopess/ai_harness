import re
from collections.abc import Sequence
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel

from harness.agent import ToolCallRecord
from harness.validators import (
    NumberReader,
    NumberToken,
    mislabeled_numbers,
    ungrounded_in,
    ungrounded_numbers,
)


class _Ints:
    """Leitor mínimo: inteiros soltos. Prova que o algoritmo não depende de formato de número."""

    def find(self, text: str) -> Sequence[NumberToken]:
        return [
            NumberToken(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())}))
            for m in re.finditer(r"(?<![\w.])\d+(?!\w)", text)
        ]


class _Dates:
    """Leitor de outro domínio (só no teste): `dd/mm/aaaa` e `aaaa-mm-dd` são UM token, cujo valor é a data.

    Mostra que a troca de dia e mês, que o leitor por dígitos solto deixaria passar, é pega só trocando o leitor.
    """

    _DMY: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w/])(\d{2})/(\d{2})/(\d{4})(?![\w/])")
    _ISO: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")

    def find(self, text: str) -> Sequence[NumberToken]:
        found = [
            NumberToken(m.group(), m.start(), m.end(), frozenset({Decimal(m[3] + m[2] + m[1])}))
            for m in self._DMY.finditer(text)
        ] + [
            NumberToken(m.group(), m.start(), m.end(), frozenset({Decimal(m[1] + m[2] + m[3])}))
            for m in self._ISO.finditer(text)
        ]
        return sorted(found, key=lambda t: t.start)


class _Unreadable:
    """Token que o leitor não sabe interpretar: `values` vazio nunca é fundamentado."""

    def find(self, text: str) -> Sequence[NumberToken]:
        return [NumberToken(m.group(), m.start(), m.end(), frozenset()) for m in re.finditer(r"#\w+", text)]


class _Deadline(BaseModel):
    due: str
    days: int


class _Result(BaseModel):
    total: int


RECORDS = (ToolCallRecord("t", "{}", _Result(total=250)),)


def test_a_number_from_the_tool_result_is_grounded() -> None:
    assert ungrounded_numbers("Total 250.", RECORDS, _Ints()) == []


def test_a_number_not_in_any_tool_result_is_reported_as_written() -> None:
    assert ungrounded_numbers("Total 251.", RECORDS, _Ints()) == ["251"]


def test_the_reader_decides_what_a_number_is() -> None:
    facts = _Deadline(due="15/03/2026", days=15)

    swapped = "Prazo em 03/15/2026."
    assert ungrounded_in(swapped, facts, _Ints()) == []  # dígitos soltos: 03, 15 e 2026 existem nos fatos
    assert ungrounded_in(swapped, facts, _Dates()) == ["03/15/2026"]  # data como unidade: a troca é pega


def test_a_date_in_another_format_still_matches_the_same_day() -> None:
    facts = _Deadline(due="2026-03-15", days=15)

    assert ungrounded_in("Prazo em 15/03/2026.", facts, _Dates()) == []


def test_a_token_the_reader_cannot_interpret_is_never_grounded() -> None:
    facts = _Deadline(due="#x", days=1)

    assert ungrounded_in("Processo #x.", facts, _Unreadable()) == ["#x"]


def test_mislabeled_uses_the_token_positions_from_the_reader() -> None:
    values = {"stock": 40, "point": 100}
    aliases = {"stock": ("estoque",), "point": ("ponto",)}
    reader: NumberReader = _Ints()

    assert mislabeled_numbers("O estoque é 100.", values, aliases, reader) == [
        "100 (next to 'stock', which is 40)"
    ]
    assert mislabeled_numbers("O estoque é 40, o ponto é 100.", values, aliases, reader) == []
