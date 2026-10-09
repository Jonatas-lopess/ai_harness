"""Reconstrói a história de um `request_id` a partir do JSONL de traces: `python -m trace_report <request_id>`.

Lado de leitura do `JsonlSink`. Genérico, sem nada de ERP (candidato a ir para o harness na fase 5).
Lê o que foi gravado, ou seja, já mascarado: o comando não tem como mostrar o que o sink não guardou.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from masking import DEFAULT_TRACE_PATH
from pricing import job_cost
from harness.tracing import Span, Trace

# Atributos que aparecem na linha do span; o resto (prompt, resultado, argumentos) só com `--full`.
SUMMARY_KEYS = (
    "name", "model", "prompt_version", "step", "attempt", "steps", "attempts", "outcome", "finish_reason",
    "tool_error", "prompt_tokens", "completion_tokens", "cost", "cost_complete", "calls_without_cost",
)  # fmt: skip

_trace_adapter = TypeAdapter(Trace)


class CorruptTraceLine(Exception):
    """Linha do JSONL que não é um trace válido (gravação cortada, arquivo editado à mão)."""


@dataclass(frozen=True)
class Found:
    line: int  # 1-based
    trace: Trace


@dataclass(frozen=True)
class Search:
    found: tuple[Found, ...]  # na ordem do arquivo
    scanned: int


def _revive_costs(trace: Trace) -> Trace:
    """No JSONL o `Decimal` virou texto (`default=str`); `job_cost` soma `Decimal`. Texto que não é número fica como está."""
    for s in trace.spans:
        cost = s.attributes.get("cost")
        if isinstance(cost, str):
            try:
                s.attributes["cost"] = Decimal(cost)
            except InvalidOperation:
                pass
    return trace


def find_traces(path: Path, request_id: str) -> Search:
    """Todos os traces com esse `request_id`. Uma linha inválida, mesmo de outro request, aborta: nunca mostra pela metade."""
    found: list[Found] = []
    scanned = 0
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                parsed = _trace_adapter.validate_json(line)
            except ValidationError as exc:
                reason = exc.errors()[0]["msg"]
                raise CorruptTraceLine(
                    f"{path}:{number}: linha inválida ({reason}). Gravação cortada? Pode ser o trace procurado; nada foi mostrado."
                ) from exc
            scanned += 1
            if parsed.trace_id == request_id:
                found.append(Found(number, _revive_costs(parsed)))
    return Search(tuple(found), scanned)


def _ms(span: Span) -> str:
    return "aberto" if span.duration_ms is None else f"{span.duration_ms:.0f} ms"


def _summary(span: Span) -> str:
    return " ".join(f"{k}={span.attributes[k]}" for k in SUMMARY_KEYS if k in span.attributes)


def _totals(trace: Trace) -> str:
    cost = job_cost(trace.spans)
    if cost.calls == 0:
        return "sem chamadas ao LLM"
    completeness = "completo" if cost.complete else f"parcial: {cost.calls_without_cost} chamada(s) sem preço"
    return (
        f"{cost.calls} chamada(s) ao LLM, {cost.prompt_tokens}→{cost.completion_tokens} tokens, "
        f"custo={cost.cost} ({completeness})"
    )


def _details(span: Span, indent: str) -> list[str]:
    lines: list[str] = []
    for key, value in span.attributes.items():
        if key in SUMMARY_KEYS or key in {"llm_calls", "cost_complete"}:
            continue
        text = value if isinstance(value, str) else _json(value)
        first, *rest = text.splitlines() or [""]
        lines.append(f"{indent}{key}: {first}")
        lines.extend(f"{indent}  {r}" for r in rest)
    return lines


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


def render(trace: Trace, *, full: bool = False) -> str:
    ids = {s.span_id for s in trace.spans}
    children: dict[str, list[Span]] = {}
    roots: list[Span] = []
    for s in trace.spans:
        if s.parent_id is None or s.parent_id not in ids:  # órfão aparece como raiz, não some
            roots.append(s)
        else:
            children.setdefault(s.parent_id, []).append(s)

    out = [f"request_id={trace.trace_id}  {_totals(trace)}"]

    def walk(span: Span, prefix: str, connector: str, child_prefix: str) -> None:
        mark = "" if span.status == "ok" else "  ERRO"
        summary = _summary(span)
        out.append(f"{prefix}{connector}{span.name}  {span.status}{mark}  {_ms(span)}" + (f"  {summary}" if summary else ""))
        kids = children.get(span.span_id, [])
        detail_indent = child_prefix + "   "
        if span.error:
            out.append(f"{detail_indent}! {span.error}")
        if full:
            out.extend(_details(span, detail_indent))
        for i, kid in enumerate(kids):
            last = i == len(kids) - 1
            walk(kid, child_prefix, "└─ " if last else "├─ ", child_prefix + ("   " if last else "│  "))

    for root in roots:
        walk(root, "", "", "")
    return "\n".join(out)


def _duplicate_warning(path: Path, request_id: str, found: Sequence[Found]) -> str:
    # As execuções anteriores também gastaram: o aviso soma todas, não só a mostrada.
    total = sum((job_cost(f.trace.spans).cost for f in found), Decimal(0))
    where = ", ".join(f"linha {f.line} ({f.trace.spans[0].started_at})" for f in found)
    return (
        f"aviso: {len(found)} traces com request_id={request_id} em {path}: {where}. "
        f"Mostrando o último. Custo somado das {len(found)} execuções: {total}."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trace_report", description="Reconstrói a história de um request_id.")
    _ = parser.add_argument("request_id")
    _ = parser.add_argument("--file", type=Path, default=DEFAULT_TRACE_PATH, help="JSONL de traces")
    _ = parser.add_argument("--full", action="store_true", help="inclui prompt, argumentos e resultados (já mascarados)")
    args = parser.parse_args(argv)
    request_id = str(args.request_id)  # pyright: ignore[reportAny]
    path = Path(str(args.file))  # pyright: ignore[reportAny]
    full = bool(args.full)  # pyright: ignore[reportAny]

    try:
        search = find_traces(path, request_id)
    except FileNotFoundError:
        print(f"arquivo de traces não existe: {path}", file=sys.stderr)
        return 2
    except CorruptTraceLine as exc:
        print(exc, file=sys.stderr)
        return 2
    if len(search.found) == 0:
        print(f"request_id={request_id} não encontrado em {path} ({search.scanned} traces lidos)", file=sys.stderr)
        return 1
    if len(search.found) > 1:
        print(_duplicate_warning(path, request_id, search.found), file=sys.stderr)
    print(render(search.found[-1].trace, full=full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
