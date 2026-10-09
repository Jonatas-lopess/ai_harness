"""O que conta como número nos textos do ERP: formato pt-BR/en, ids com letra, separadores de milhar.

Regra do pack, não do harness (`harness.validators` só recebe o leitor). Outro domínio lê outra coisa:
o Legal tem datas e números de processo, que este leitor entenderia errado.
"""

import re
from collections.abc import Sequence
from decimal import Decimal

from harness.validators import Token

# Número isolado: dígito colado em letra/underscore/dígito é identificador ("A12", "B07"), não número.
# Separadores só entram se seguidos de dígito, então o ponto final de uma frase fica de fora.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)*(?![A-Za-z0-9_])")
_SEPARATOR = re.compile(r"[.,]")


def _values(token: str) -> frozenset[Decimal]:
    """Valores que o texto do número pode representar. "1.250" é 1250 (pt-BR) ou 1,25 (en): ambíguo."""
    seps = _SEPARATOR.findall(token)
    if not seps:
        return frozenset({Decimal(token)})
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
    return frozenset(values)


class ErpNumberReader:
    def find(self, text: str) -> Sequence[Token]:
        return [Token(m.group(), m.start(), m.end(), _values(m.group())) for m in _NUMBER.finditer(text)]


ERP_NUMBERS = ErpNumberReader()
