from datetime import date
from decimal import Decimal

import psycopg
from pytest import fixture, mark

from closing import closing_facts
from closing_job import PROMPT_VERSION, run_closing_job
from extract import Completion, Usage
from settings import get_settings
from tests.test_refill_job import ScriptedClient
from tools import connect_readonly

pytestmark = mark.integration


@fixture
def conn():
    with connect_readonly(get_settings().database_url.get_secret_value()) as c:
        yield c


def test_closing_totals_for_a_known_day(conn: psycopg.Connection) -> None:
    # Dia 20: 150*10 + 150*20 + 15*30 + 150*40 = 10950; 150+150+15+150 = 465 unidades.
    facts = closing_facts(conn, date(2026, 1, 20))

    assert facts is not None
    assert facts.revenue == Decimal("10950.00")
    assert facts.units == 465
    assert facts.top_product == "received-po"  # 150 * 40 = 6000


def test_closing_only_counts_that_day(conn: psycopg.Connection) -> None:
    # Dia 31 só tem a venda do produto 3 (999 * 30); as de 10 e 20/01 ficam de fora.
    facts = closing_facts(conn, date(2026, 1, 31))

    assert facts is not None
    assert (facts.revenue, facts.units, facts.top_product) == (Decimal("29970.00"), 999, "false-alarm")


def test_day_without_sales_has_no_facts(conn: psycopg.Connection) -> None:
    assert closing_facts(conn, date(2026, 1, 15)) is None


def test_day_without_sales_never_calls_the_model(conn: psycopg.Connection) -> None:
    client = ScriptedClient()  # qualquer chamada estoura (lista vazia)

    report = run_closing_job(client, conn, date(2026, 1, 15), model="m")

    assert report.facts is None and report.summary is None and report.error is None
    assert client.calls == []


def test_job_writes_a_validated_summary(conn: psycopg.Connection) -> None:
    text = "Faturamento de R$ 10.950,00 com 465 unidades; destaque para received-po."
    client = ScriptedClient(Completion(f'{{"rationale": "{text}"}}', "stop", usage=Usage(10, 5)))

    report = run_closing_job(client, conn, date(2026, 1, 20), model="m")

    assert report.summary == text
    assert report.prompt_version == PROMPT_VERSION
    assert report.usage == Usage(10, 5)
