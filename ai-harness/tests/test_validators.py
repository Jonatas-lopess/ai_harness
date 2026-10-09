import re
from collections.abc import Hashable, Sequence
from datetime import date
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel

from harness.agent import ToolCallRecord
from harness.validators import (
    Token,
    TokenReader,
    mislabeled_tokens,
    ungrounded_in,
    ungrounded_tokens,
)


class _Ints:
    """Leitor mínimo: inteiros soltos. Prova que o algoritmo não depende de formato de número."""

    def find(self, text: str) -> Sequence[Token]:
        return [
            Token(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())}))
            for m in re.finditer(r"(?<![\w.])\d+(?!\w)", text)
        ]


class _Dates:
    """Leitor de outro domínio (só no teste): `dd/mm/aaaa` e `aaaa-mm-dd` são UM token, cujo valor é um `date`.

    Mostra que a troca de dia e mês, que o leitor por dígitos soltos deixaria passar, é pega só trocando o leitor.
    """

    _DMY: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w/])(\d{2})/(\d{2})/(\d{4})(?![\w/])")
    _ISO: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")

    @staticmethod
    def _token(m: re.Match[str], y: int, mo: int, d: int) -> Token:
        try:
            values: frozenset[Hashable] = frozenset({date(y, mo, d)})
        except ValueError:  # data impossível ("03/15/2026" lido como dia/mês): não sei ler, nunca é fundamentada
            values = frozenset()
        return Token(m.group(), m.start(), m.end(), values)

    def find(self, text: str) -> Sequence[Token]:
        found = [self._token(m, int(m[3]), int(m[2]), int(m[1])) for m in self._DMY.finditer(text)] + [
            self._token(m, int(m[1]), int(m[2]), int(m[3])) for m in self._ISO.finditer(text)
        ]
        return sorted(found, key=lambda t: t.start)


class _Cases:
    """Número de processo: identificador, não número. O valor é a própria string (zeros à esquerda importam)."""

    _CNJ: ClassVar[re.Pattern[str]] = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

    def find(self, text: str) -> Sequence[Token]:
        return [Token(m.group(), m.start(), m.end(), frozenset({m.group()})) for m in self._CNJ.finditer(text)]


class _Both:
    """Composição feita pelo PACK: junta leitores e descarta o token que está dentro de outro (o "15" da data)."""

    def __init__(self, *readers: TokenReader) -> None:
        self._readers: tuple[TokenReader, ...] = readers

    def find(self, text: str) -> Sequence[Token]:
        tokens = [t for r in self._readers for t in r.find(text)]
        kept = [
            t
            for t in tokens
            if not any(o is not t and o.start <= t.start and t.end <= o.end and (o.end - o.start) > (t.end - t.start) for o in tokens)
        ]
        return sorted(kept, key=lambda t: t.start)


class _Unreadable:
    """Token que o leitor não sabe interpretar: `values` vazio nunca é fundamentado."""

    def find(self, text: str) -> Sequence[Token]:
        return [Token(m.group(), m.start(), m.end(), frozenset()) for m in re.finditer(r"#\w+", text)]


class _Deadline(BaseModel):
    due: str
    days: int


class _Case(BaseModel):
    due: str
    days: int
    case_number: str


class _Result(BaseModel):
    total: int


RECORDS = (ToolCallRecord("t", "{}", _Result(total=250)),)


def test_a_number_from_the_tool_result_is_grounded() -> None:
    assert ungrounded_tokens("Total 250.", RECORDS, _Ints()) == []


def test_a_number_not_in_any_tool_result_is_reported_as_written() -> None:
    assert ungrounded_tokens("Total 251.", RECORDS, _Ints()) == ["251"]


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
    reader: TokenReader = _Ints()

    assert mislabeled_tokens("O estoque é 100.", values, aliases, reader) == [
        "100 (next to 'stock', which is 40)"
    ]
    assert mislabeled_tokens("O estoque é 40, o ponto é 100.", values, aliases, reader) == []


# --- valores que não são Decimal -------------------------------------------------------------------------------------


def test_a_quantity_never_grounds_a_date_even_when_the_digits_match() -> None:
    class _Qty(BaseModel):
        total: int

    assert ungrounded_in("Prazo em 15/03/2026.", _Qty(total=20260315), _Dates()) == ["15/03/2026"]


def test_a_case_number_in_the_facts_grounds_the_same_case_number_in_the_text() -> None:
    facts = _Deadline(due="x", days=1)
    case = _Case(due="x", days=1, case_number="0001234-56.2024.8.26.0100")

    assert ungrounded_in("Processo 0001234-56.2024.8.26.0100.", case, _Cases()) == []
    assert ungrounded_in("Processo 0001234-56.2024.8.26.0100.", facts, _Cases()) == ["0001234-56.2024.8.26.0100"]


def test_a_case_number_with_one_wrong_digit_is_rejected() -> None:
    case = _Case(due="x", days=1, case_number="0001234-56.2024.8.26.0100")

    assert ungrounded_in("Processo 0001234-56.2024.8.26.0101.", case, _Cases()) == ["0001234-56.2024.8.26.0101"]


def test_the_pack_composes_readers_and_the_legal_sentence_is_grounded() -> None:
    facts = _Case(due="2026-03-15", days=15, case_number="0001234-56.2024.8.26.0100")
    reader = _Both(_Dates(), _Cases(), _Ints())
    sentence = "Prazo final em 15/03/2026 (15 dias úteis), processo 0001234-56.2024.8.26.0100."

    assert [t.text for t in reader.find(sentence)] == ["15/03/2026", "15", "0001234-56.2024.8.26.0100"]
    assert ungrounded_in(sentence, facts, reader) == []
    assert ungrounded_in(sentence.replace("15/03/2026", "03/15/2026"), facts, reader) == ["03/15/2026"]
    assert ungrounded_in(sentence.replace("(15 dias", "(16 dias"), facts, reader) == ["16"]


def test_mislabeled_works_with_values_that_are_dates() -> None:
    values = {"due": date(2026, 3, 15), "hearing": date(2026, 3, 20)}
    aliases = {"due": ("prazo",), "hearing": ("audiência",)}

    assert mislabeled_tokens("A audiência é em 15/03/2026.", values, aliases, _Dates()) == [
        "15/03/2026 (next to 'hearing', which is 2026-03-20)"
    ]
    assert mislabeled_tokens("Prazo em 15/03/2026, audiência em 20/03/2026.", values, aliases, _Dates()) == []


def test_an_impossible_date_is_rejected_not_a_crash() -> None:
    facts = _Deadline(due="2026-03-15", days=15)

    assert ungrounded_in("Prazo em 31/02/2026.", facts, _Dates()) == ["31/02/2026"]
