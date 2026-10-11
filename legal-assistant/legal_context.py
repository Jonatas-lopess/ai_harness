"""Contexto das tools do Legal: o que o harness repassa a cada tool sem olhar dentro."""

from dataclasses import dataclass
from datetime import date

import psycopg


@dataclass(frozen=True)
class LegalContext:
    """O modelo nunca escolhe estes valores (ex.: `as_of`, `user_id`).

    `user_id` não tem padrão de propósito: esquecer de informá-lo é erro alto (`TypeError`), não
    uma consulta sem filtro. O papel (`role`) entra na fase 8, quando alguma regra depender dele.
    """

    conn: psycopg.Connection
    as_of: date
    user_id: str


def connect_readonly(url: str) -> psycopg.Connection:
    """Conexão em que o Postgres recusa qualquer escrita, mesmo que uma tool tente."""
    return psycopg.connect(url, options="-c default_transaction_read_only=on")
