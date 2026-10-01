import psycopg
from pytest import mark

from settings import get_settings


@mark.integration
def test_db_connection():
    url = get_settings().database_url

    with psycopg.connect(url.get_secret_value()) as conn:
        cur = conn.cursor()
        result = cur.execute("SELECT count(*) FROM products").fetchone()

    assert result is not None
    assert result[0] >= 1
