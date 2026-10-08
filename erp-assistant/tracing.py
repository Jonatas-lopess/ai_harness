"""Tracing mínimo: uma execução = um trace (árvore de spans) com `request_id`.

Genérico, sem nada de ERP (candidato a ir para o harness na fase 5). Formato parecido com OpenTelemetry
(trace_id, span_id, parent_id) para trocar o destino depois sem reescrever quem instrumenta.
"""

import json
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    started_at: str  # ISO 8601 UTC
    duration_ms: float | None = None  # None = span ainda aberto
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def set(self, **attributes: object) -> None:
        self.attributes.update(attributes)


@dataclass
class Trace:
    trace_id: str  # é o request_id da execução
    spans: list[Span] = field(default_factory=list)  # na ordem de abertura: pai antes dos filhos


class TraceSink(Protocol):
    def write(self, trace: Trace) -> None: ...


class MemorySink:
    """Guarda os traces em memória (testes)."""

    def __init__(self) -> None:
        self.traces: list[Trace] = []

    def write(self, trace: Trace) -> None:
        self.traces.append(trace)


class JsonlSink:
    """Um trace por linha em um arquivo JSONL."""

    def __init__(self, path: Path) -> None:
        self.path: Path = path

    def write(self, trace: Trace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # default=str: atributo que não é JSON (Decimal, date) vira texto em vez de derrubar a gravação.
        line = json.dumps(asdict(trace), ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as f:
            _ = f.write(line + "\n")


@dataclass(frozen=True)
class _Active:
    trace: Trace
    span: Span


# Cada task do asyncio enxerga o seu valor: é assim que `span()` acha o pai sem receber o trace por parâmetro.
_active: ContextVar[_Active | None] = ContextVar("tracing_active", default=None)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def _open(
    trace: Trace, name: str, parent_id: str | None, attributes: dict[str, object], clock: Callable[[], float]
) -> Generator[Span]:
    span = Span(trace.trace_id, _new_id(), parent_id, name, _now(), attributes=dict(attributes))
    trace.spans.append(span)
    token = _active.set(_Active(trace, span))
    start = clock()
    try:
        yield span
    except BaseException as exc:  # inclui CancelledError: cancelado também é causa
        span.status = "error"
        span.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        span.duration_ms = (clock() - start) * 1000
        _active.reset(token)


@contextmanager
def trace(
    name: str,
    sink: TraceSink,
    /,
    *,
    request_id: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
    **attributes: object,
) -> Generator[Span]:
    """Abre um trace e seu span raiz. Ao sair, mesmo com exceção, grava no `sink`."""
    t = Trace(request_id or _new_id())
    try:
        with _open(t, name, None, attributes, clock) as root:
            yield root
    finally:
        sink.write(t)


@contextmanager
def span(
    name: str, /, *, clock: Callable[[], float] = time.perf_counter, **attributes: object
) -> Generator[Span]:
    """Abre um span filho do span ativo. `name` é só posicional: `name=` vira atributo (ex.: nome da tool). Sem trace ativo, o código roda igual e nada é gravado."""
    current = _active.get()
    if current is None:
        yield Span("-", "-", None, name, _now(), attributes=dict(attributes))
        return
    with _open(current.trace, name, current.span.span_id, attributes, clock) as s:
        yield s
