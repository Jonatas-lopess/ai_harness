import json
from datetime import date
from pathlib import Path
from typing import cast

from pytest import CaptureFixture, mark

from harness.providers.groq import GroqClient
from harness.masking import production_sink
from refill_job import run_refill_job
from settings import get_settings
from erp_context import connect_readonly
from trace_report import main
from harness.tracing import JsonlSink, trace

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


def test_real_job_trace_has_cost_model_and_request_id(tmp_path: Path) -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    path = tmp_path / "traces.jsonl"

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        with trace("real-refill", JsonlSink(path), request_id="real-2"):
            report = run_refill_job(client, conn, AS_OF, model=MODEL)

    [line] = path.read_text(encoding="utf-8").splitlines()
    recorded = cast("dict[str, object]", json.loads(line))
    spans = cast("list[dict[str, object]]", recorded["spans"])
    [job] = [cast("dict[str, object]", s["attributes"]) for s in spans if s["name"] == "refill_job"]
    print(f"\nrequest_id={recorded['trace_id']} job={ {k: job[k] for k in sorted(job)} }")

    assert recorded["trace_id"] == "real-2"
    assert job["model"] == MODEL and job["prompt_version"] == report.prompt_version
    assert job["prompt_tokens"] == report.usage.prompt_tokens
    assert job["cost_complete"] is True
    assert float(str(job["cost"])) > 0


def test_real_job_story_is_rebuilt_from_the_request_id(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    path = tmp_path / "traces.jsonl"

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        with trace("real-refill", production_sink(path), request_id="real-3"):
            report = run_refill_job(client, conn, AS_OF, model=MODEL)

    _ = capsys.readouterr()
    assert main(["real-3", "--file", str(path), "--full"]) == 0
    story = capsys.readouterr().out
    with capsys.disabled():
        print(f"\n{story}")

    assert story.startswith("request_id=real-3")
    assert f"model={MODEL}" in story and f"prompt_version={report.prompt_version}" in story
    assert f"{report.usage.prompt_tokens}→{report.usage.completion_tokens} tokens" in story
    assert "(completo)" in story
    assert all(i.rationale in story for i in report.items if i.rationale)
