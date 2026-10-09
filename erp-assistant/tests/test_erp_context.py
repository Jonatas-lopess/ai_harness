import psycopg
from pytest import mark, raises

from erp_context import connect_readonly
from settings import get_settings


@mark.integration
def test_readonly_connection_rejects_writes():
    url = get_settings().database_url.get_secret_value()
    with connect_readonly(url) as conn, raises(psycopg.errors.ReadOnlySqlTransaction):
        _ = conn.execute("UPDATE products SET stock = 0")
