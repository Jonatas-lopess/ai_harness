from datetime import date

from pytest import mark

from closing_job import run_closing_job
from groq_client import GroqClient
from settings import get_settings
from tools import connect_readonly

MODEL = "openai/gpt-oss-120b"

pytestmark = mark.integration


def test_real_closing_summary_is_grounded() -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        report = run_closing_job(client, conn, date(2026, 1, 20), model=MODEL)

    print(f"\nusage={report.usage} prompt={report.prompt_version}\nsummary={report.summary}")
    assert report.facts is not None
    assert report.summary is not None and report.error is None
