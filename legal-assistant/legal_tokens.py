"""O que conta como "valor" nos textos do Legal: datas, números de processo e inteiros.

Regra do pack, não do harness (`harness.validators` só recebe o leitor). Três leitores pequenos e uma composição:
um pedaço de texto pode casar com dois leitores (o "13" dentro de "13/03/2026"), e quem decide qual vale é o pack.
"""

import re
from collections.abc import Hashable, Sequence
from datetime import date
from decimal import Decimal
from typing import ClassVar

from harness.validators import Token, TokenReader


class DateReader:
    """`dd/mm/aaaa` e `aaaa-mm-dd` são UM token, com valor `date` (nunca um `Decimal`: uma quantidade não fundamenta data)."""

    _DMY: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w/])(\d{2})/(\d{2})/(\d{4})(?![\w/])")
    _ISO: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")

    @staticmethod
    def _token(m: re.Match[str], year: int, month: int, day: int) -> Token:
        try:
            values: frozenset[Hashable] = frozenset({date(year, month, day)})
        except ValueError:
            # "03/13/2026" lido como dia/mês é o mês 13. O texto vem do modelo: não pode lançar exceção. Sem valor, nunca é fundamentado.
            values = frozenset()
        return Token(m.group(), m.start(), m.end(), values)

    def find(self, text: str) -> Sequence[Token]:
        found = [self._token(m, int(m[3]), int(m[2]), int(m[1])) for m in self._DMY.finditer(text)]
        found += [self._token(m, int(m[1]), int(m[2]), int(m[3])) for m in self._ISO.finditer(text)]
        return sorted(found, key=lambda t: t.start)


class CaseNumberReader:
    """Número CNJ: identificador, não número. O valor é a própria string, porque zeros à esquerda importam."""

    _CNJ: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w.-])\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?![\w-]|\.\d)")

    def find(self, text: str) -> Sequence[Token]:
        return [Token(m.group(), m.start(), m.end(), frozenset({m.group()})) for m in self._CNJ.finditer(text)]


class IntegerReader:
    """Inteiro solto ("3 dias"). Número derivado que o modelo calcula por conta própria cai aqui e é rejeitado."""

    _INT: ClassVar[re.Pattern[str]] = re.compile(r"(?<![\w.,-])\d+(?![\w,-])")

    def find(self, text: str) -> Sequence[Token]:
        return [Token(m.group(), m.start(), m.end(), frozenset({Decimal(m.group())})) for m in self._INT.finditer(text)]


class ComposedReader:
    """Junta leitores e descarta o token que está dentro de outro maior (o "13" e o "03" de "13/03/2026")."""

    def __init__(self, *readers: TokenReader) -> None:
        self._readers: tuple[TokenReader, ...] = readers

    def find(self, text: str) -> Sequence[Token]:
        tokens = [t for reader in self._readers for t in reader.find(text)]
        kept = [t for t in tokens if not any(_is_inside(t, other) for other in tokens)]
        return sorted(kept, key=lambda t: t.start)


def _is_inside(inner: Token, outer: Token) -> bool:
    return outer.start <= inner.start and inner.end <= outer.end and (outer.end - outer.start) > (inner.end - inner.start)


LEGAL_TOKENS = ComposedReader(DateReader(), CaseNumberReader(), IntegerReader())
