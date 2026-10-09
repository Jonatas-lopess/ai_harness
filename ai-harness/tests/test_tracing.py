import asyncio
import json
from pathlib import Path

from pytest import raises

from harness.tracing import JsonlSink, MemorySink, Trace, current_trace, descendants, span, trace


def only(sink: MemorySink) -> Trace:
    assert len(sink.traces) == 1
    return sink.traces[0]


def test_root_span_gets_the_request_id_and_a_duration() -> None:
    sink = MemorySink()
    with trace("job", sink, request_id="req-1"):
        pass
    t = only(sink)
    assert t.trace_id == "req-1"
    assert [s.name for s in t.spans] == ["job"]
    assert t.spans[0].parent_id is None
    assert t.spans[0].duration_ms is not None
    assert t.spans[0].status == "ok"


def test_request_id_is_generated_and_unique_when_not_given() -> None:
    sink = MemorySink()
    with trace("a", sink):
        pass
    with trace("a", sink):
        pass
    first, second = sink.traces
    assert first.trace_id and second.trace_id
    assert first.trace_id != second.trace_id


def test_children_point_to_their_parent_and_siblings_share_it() -> None:
    sink = MemorySink()
    with trace("job", sink):
        with span("llm"):
            with span("inner"):
                pass
        with span("tool"):  # irmão de "llm": o pai voltou a ser o raiz
            pass
    root, llm, inner, tool = only(sink).spans
    assert llm.parent_id == root.span_id
    assert inner.parent_id == llm.span_id
    assert tool.parent_id == root.span_id
    assert {s.trace_id for s in (root, llm, inner, tool)} == {only(sink).trace_id}


def test_error_is_recorded_with_duration_and_still_raised_and_written() -> None:
    sink = MemorySink()
    with raises(RuntimeError, match="provider down"):
        with trace("job", sink):
            with span("llm"):
                raise RuntimeError("provider down")
    root, llm = only(sink).spans
    assert llm.status == "error"
    assert llm.error == "RuntimeError: provider down"
    assert llm.duration_ms is not None
    assert root.status == "error"  # o erro atravessou o raiz também


def test_attributes_from_open_and_from_set() -> None:
    sink = MemorySink()
    with trace("job", sink, prompt_version="v1"):
        with span("llm", model="m") as s:
            s.set(prompt_tokens=10)
    root, llm = only(sink).spans
    assert root.attributes == {"prompt_version": "v1"}
    assert llm.attributes == {"model": "m", "prompt_tokens": 10}


def test_duration_comes_from_the_injected_clock() -> None:
    ticks = iter([1.0, 3.5])
    sink = MemorySink()
    with trace("job", sink, clock=lambda: next(ticks)):
        pass
    assert only(sink).spans[0].duration_ms == 2500.0


def test_span_without_active_trace_runs_and_records_nothing() -> None:
    with span("orphan", x=1) as s:
        s.set(y=2)
    assert s.attributes == {"x": 1, "y": 2}


def test_concurrent_traces_do_not_mix_parents() -> None:
    sink = MemorySink()

    async def job(request_id: str) -> None:
        with trace("job", sink, request_id=request_id):
            await asyncio.sleep(0)  # deixa o outro job abrir o trace antes de eu abrir meu filho
            with span("llm"):
                await asyncio.sleep(0)
                with span("tool"):
                    await asyncio.sleep(0)

    async def main() -> None:
        _ = await asyncio.gather(job("a"), job("b"))

    asyncio.run(main())

    assert len(sink.traces) == 2
    for t in sink.traces:
        root, llm, tool = t.spans
        assert llm.parent_id == root.span_id
        assert tool.parent_id == llm.span_id
        assert {s.trace_id for s in t.spans} == {t.trace_id}
    assert {t.trace_id for t in sink.traces} == {"a", "b"}


def test_jsonl_sink_writes_one_trace_per_line(tmp_path: Path) -> None:
    from decimal import Decimal

    path = tmp_path / "deep" / "traces.jsonl"
    sink = JsonlSink(path)
    for rid in ("r1", "r2"):
        with trace("job", sink, request_id=rid, cost=Decimal("0.0003")):
            with span("llm"):
                pass
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])  # pyright: ignore[reportAny]
    assert first["trace_id"] == "r1"
    assert [s["name"] for s in first["spans"]] == ["job", "llm"]  # pyright: ignore[reportAny]
    assert first["spans"][0]["attributes"] == {"cost": "0.0003"}  # Decimal virou texto, não derrubou


def test_current_trace_is_the_active_one_and_none_outside() -> None:
    assert current_trace() is None
    sink = MemorySink()
    with trace("job", sink, request_id="r"):
        active = current_trace()
        assert active is not None and active.trace_id == "r"
    assert current_trace() is None


def test_descendants_returns_the_whole_subtree_without_the_root_of_it() -> None:
    sink = MemorySink()
    with trace("root", sink):
        with span("a") as a:
            with span("a1"):
                with span("a1x"):
                    pass
        with span("b"):
            pass
    t = only(sink)
    assert sorted(s.name for s in descendants(t, a.span_id)) == ["a1", "a1x"]
    assert len(descendants(t, t.spans[0].span_id)) == 4
