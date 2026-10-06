from datetime import date

from pytest import mark

from groq_client import GroqClient
from refill_job import run_refill_job
from settings import get_settings
from tools import connect_readonly

MODEL = "openai/gpt-oss-120b"
AS_OF = date(2026, 1, 31)

pytestmark = mark.integration


def test_real_job_writes_grounded_rationales() -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        report = run_refill_job(client, conn, AS_OF, model=MODEL)

    print(f"\nusage={report.usage} prompt={report.prompt_version}")
    for item in report.items:
        print(f"{item.product_id} {item.name} qty={item.suggested_qty}\n  rationale={item.rationale}\n  error={item.rationale_error}")

    assert report.items
    assert all(i.rationale is not None for i in report.items)
