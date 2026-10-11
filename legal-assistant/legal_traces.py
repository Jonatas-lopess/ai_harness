"""Onde o Legal grava os traces. O caminho é de deploy; o mecanismo (`production_sink`) é do harness.

Arquivo próprio, nunca o do ERP: os dois packs não compartilham dado. O trace guarda dado do cliente (número do
processo, texto das movimentações) porque é ele que permite explicar uma frase do digest; por isso fica fora do Git e,
com dado real, precisa de retenção e acesso definidos antes (ver README).
"""

from pathlib import Path

from harness.masking import production_sink
from harness.tracing import TraceSink

TRACE_PATH = Path(__file__).parent / "traces" / "traces.jsonl"


def legal_trace_sink(path: Path = TRACE_PATH) -> TraceSink:
    return production_sink(path)
