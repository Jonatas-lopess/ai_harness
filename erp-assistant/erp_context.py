"""Contexto das tools do ERP: o que o harness repassa a cada tool sem olhar dentro."""

from dataclasses import dataclass
from datetime import date

import psycopg


@dataclass(frozen=True)
class ErpContext:
    """O modelo nunca escolhe estes valores (ex.: `as_of`)."""

    conn: psycopg.Connection
    as_of: date


def connect_readonly(url: str) -> psycopg.Connection:
    """Conexão em que o Postgres recusa qualquer escrita, mesmo que uma tool tente.

    Defesa em profundidade; em produção o ideal é também uma role sem INSERT/UPDATE/DELETE.
    """
    return psycopg.connect(url, options="-c default_transaction_read_only=on")
