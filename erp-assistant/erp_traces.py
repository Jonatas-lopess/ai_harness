"""Onde o ERP grava os traces. O caminho é de deploy; o mecanismo (`production_sink`) é do harness."""

from pathlib import Path

from harness.masking import production_sink
from harness.tracing import TraceSink

# Fora do Git (ver .gitignore): mesmo mascarado, trace é dado de execução.
TRACE_PATH = Path(__file__).parent / "traces" / "traces.jsonl"


def erp_trace_sink(path: Path = TRACE_PATH) -> TraceSink:
    return production_sink(path)
