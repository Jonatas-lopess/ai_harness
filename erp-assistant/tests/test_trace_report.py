from decimal import Decimal
from pathlib import Path
from typing import Literal

from pytest import CaptureFixture, raises

from masking import production_sink
from pricing import costed_span
from trace_report import CorruptTraceLine, find_traces, main, render
from tracing import JsonlSink, Span, Trace, span, trace


def _span(
    span_id: str,
    parent_id: str | None,
    name: str,
    *,
    trace_id: str = "req-1",
    status: Literal["ok", "error"] = "ok",
    error: str | None = None,
    **attributes: object,
) -> Span:
    return Span(
        trace_id, span_id, parent_id, name, "2026-10-08T12:00:00+00:00", 10.0,
        status, error, dict(attributes),
    )  # fmt: skip


def _sample(trace_id: str = "req-1", cost: str | None = "0.0002") -> Trace:
    call_attrs: dict[str, object] = {"step": 1, "prompt_tokens": 100, "completion_tokens": 20}
    if cost is not None:
        call_attrs["cost"] = cost
    call = _span("c", "b", "llm_call", trace_id=trace_id, content="oi")
    call.attributes.update(call_attrs)
    return Trace(
        trace_id,
        [
            _span("a", None, "refill_job", trace_id=trace_id, model="m"),
            _span("b", "a", "narrate", trace_id=trace_id, outcome="accepted", attempts=1),
            call,
            _span("d", "b", "validate", trace_id=trace_id, status="error", error="ValueError: 7 não está nos fatos"),
        ],
    )


def _write(path: Path, *traces: Trace) -> None:
    sink = JsonlSink(path)
    for t in traces:
        sink.write(t)


def test_render_rebuilds_the_tree_from_parent_ids(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample())

    [hit] = find_traces(path, "req-1").found
    lines = render(hit.trace).splitlines()

    assert lines[0] == "request_id=req-1  1 chamada(s) ao LLM, 100→20 tokens, custo=0.0002 (completo)"
    assert lines[1] == "refill_job  ok  10 ms  model=m"
    assert lines[2] == "└─ narrate  ok  10 ms  attempts=1 outcome=accepted"
    assert lines[3] == "   ├─ llm_call  ok  10 ms  step=1 prompt_tokens=100 completion_tokens=20 cost=0.0002"
    assert lines[4] == "   └─ validate  error  ERRO  10 ms"
    assert lines[5].endswith("! ValueError: 7 não está nos fatos")


def test_the_error_is_the_cause_shown_under_the_span(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample())

    [hit] = find_traces(path, "req-1").found

    assert "ERRO" in render(hit.trace)
    assert "ValueError: 7 não está nos fatos" in render(hit.trace)


def test_prompt_and_results_only_with_full(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample())
    [hit] = find_traces(path, "req-1").found

    assert "content" not in render(hit.trace)
    assert "content: oi" in render(hit.trace, full=True)


def test_cost_is_flagged_partial_when_a_call_has_no_price(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample(cost=None))
    [hit] = find_traces(path, "req-1").found

    assert "(parcial: 1 chamada(s) sem preço)" in render(hit.trace)


def test_orphan_span_is_shown_as_a_root_not_dropped() -> None:
    t = Trace("req-1", [_span("x", "missing-parent", "lost")])

    assert "lost  ok" in render(t)


def test_last_trace_wins_and_warning_sums_the_cost_of_all(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    path = tmp_path / "t.jsonl"
    first, second = _sample(cost="0.0002"), _sample(cost="0.0003")
    second.spans[0].attributes["model"] = "segunda"
    _write(path, first, _sample("outro"), second)

    code = main(["req-1", "--file", str(path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "model=segunda" in captured.out
    assert "2 traces com request_id=req-1" in captured.err
    assert "linha 1" in captured.err and "linha 3" in captured.err
    assert "0.0005" in captured.err


def test_unknown_request_id_exits_1_and_says_how_many_were_read(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample("a"), _sample("b"))

    code = main(["nope", "--file", str(path)])

    err = capsys.readouterr().err
    assert code == 1
    assert "request_id=nope não encontrado" in err
    assert "(2 traces lidos)" in err


def test_missing_file_is_not_the_same_as_not_found(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    code = main(["req-1", "--file", str(tmp_path / "none.jsonl")])

    assert code == 2
    assert "arquivo de traces não existe" in capsys.readouterr().err


def test_truncated_line_aborts_even_for_another_request_id(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Decisão do autor (A): linha inválida derruba a consulta; nunca mostra trace pelo meio."""
    path = tmp_path / "t.jsonl"
    _write(path, _sample("good-1"))
    with path.open("a", encoding="utf-8") as f:
        _ = f.write('{"trace_id": "cut", "spans": [{"trace_id": "cu\n')
    _write(path, _sample("good-2"))

    with raises(CorruptTraceLine, match=r"t\.jsonl:2: linha inválida"):
        _ = find_traces(path, "good-2")

    assert main(["good-2", "--file", str(path)]) == 2
    err = capsys.readouterr().err
    assert ":2:" in err and "Pode ser o trace procurado" in err


def test_json_that_is_not_a_trace_is_also_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _ = path.write_text('{"hello": 1}\n', encoding="utf-8")

    with raises(CorruptTraceLine, match=r"t\.jsonl:1: linha inválida \(Field required\)"):
        _ = find_traces(path, "x")


def test_end_to_end_production_sink_then_report_without_personal_data(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"

    with trace("job", production_sink(path), request_id="e2e"):
        with costed_span("refill_job", model="m", prompt_version="v1"):
            with span("llm_call", step=1, prompt_tokens=10, completion_tokens=5, cost=Decimal("0.001"), content="CPF 123.456.789-09"):
                pass

    [hit] = find_traces(path, "e2e").found
    out = render(hit.trace, full=True)

    assert "123.456.789-09" not in path.read_text(encoding="utf-8")
    assert "content: CPF [cpf]" in out
    assert "custo=0.001" in out


def test_masked_cost_counts_as_unknown_not_complete(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _write(path, _sample(cost="[masked:Decimal]"))
    [hit] = find_traces(path, "req-1").found

    out = render(hit.trace)

    assert "custo=0 (parcial: 1 chamada(s) sem preço)" in out
