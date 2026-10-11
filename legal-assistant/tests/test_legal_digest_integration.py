from collections.abc import Iterator
from datetime import date

import psycopg
from harness.providers.groq import GroqClient
from pytest import fixture, mark

from legal_context import LegalContext, connect_readonly
from legal_digest import run_digest_job
from settings import get_settings

MODEL = "openai/gpt-oss-120b"

pytestmark = mark.integration


@fixture
def conn() -> Iterator[psycopg.Connection]:
    with connect_readonly(get_settings().database_url.get_secret_value()) as c:
        yield c


def test_real_digest_sentences_carry_the_record_dates(conn: psycopg.Connection) -> None:
    client = GroqClient(get_settings().groq_api_key.get_secret_value())
    ctx = LegalContext(conn=conn, as_of=date(2026, 3, 10), user_id="ana")

    # days=3: o vencido (deadline:3) e o de 13/03 (deadline:1); duas chamadas só, por causa da quota.
    digest = run_digest_job(client, ctx, model=MODEL, days=3)

    for item in digest.items:
        print(f"\n{item.source_ref} [{item.situation}] attempts-warning={item.warning}\n  {item.sentence}")
    print(f"usage={digest.usage}")
    assert [i.source_ref for i in digest.items] == ["deadline:3", "deadline:1"]
    assert all(i.sentence is not None and i.warning is None for i in digest.items)
