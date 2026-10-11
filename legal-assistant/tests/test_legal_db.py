"""O seed é o contrato das armadilhas: se alguém o editar, estes testes dizem qual caso sumiu."""

from datetime import date

import psycopg
from pytest import fixture, mark

from settings import get_settings

AS_OF = date(2026, 3, 10)


@fixture
def conn():
    with psycopg.connect(get_settings().database_url.get_secret_value()) as connection:
        yield connection


@mark.integration
def test_deadline_due_in_three_days(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM deadlines WHERE status = 'open' AND due_date = %s", (date(2026, 3, 13),)
    ).fetchall()
    assert len(rows) == 1


@mark.integration
def test_overdue_deadline_still_open(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM deadlines WHERE status = 'open' AND due_date < %s", (AS_OF,)
    ).fetchall()
    assert len(rows) == 1


@mark.integration
def test_matter_without_events(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT m.id FROM matters m LEFT JOIN events e ON e.matter_id = m.id "
        "WHERE e.id IS NULL AND m.responsible_user = 'ana'"
    ).fetchall()
    assert len(rows) == 1


@mark.integration
def test_matter_of_another_responsible(conn: psycopg.Connection) -> None:
    users = {r[0] for r in conn.execute("SELECT DISTINCT responsible_user FROM matters").fetchall()}
    assert users == {"ana", "bruno"}


@mark.integration
def test_event_with_text_that_gives_orders_to_the_model(conn: psycopg.Connection) -> None:
    rows = conn.execute("SELECT id FROM events WHERE description ILIKE 'Ignore as instruções%'").fetchall()
    assert len(rows) == 1
