"""Mascara o trace antes de gravar: genérico, sem nada de ERP (candidato a ir para o harness na fase 5).

Três níveis por chave de atributo, com allowlist (chave desconhecida é mascarada: falha fechado):
- `keep_keys`: passa como está (números, ids, enums, nome de modelo; o que a checagem de fundamento precisa);
- `scrub_keys`: texto livre ou JSON que se quer manter legível; só os padrões de dado pessoal são trocados;
- qualquer outra: o valor inteiro vira `[masked:<tipo>]`.

Limite: padrão em texto é melhor esforço. Só reconhece CPF/CNPJ (formatados ou com 11/14 dígitos soltos), e-mail e
telefone brasileiro formatado; nome de pessoa e telefone sem formatação passam. A proteção de verdade é a allowlist
e não mandar dado real durante o estudo.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from tracing import Span, Trace, TraceSink

# Do mais específico ao mais geral: CNPJ antes de CPF, para o CNPJ não ser comido em pedaços.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cnpj", re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|(?<![\d.,])\d{14}(?![\d.,])")),
    ("cpf", re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|(?<![\d.,])\d{11}(?![\d.,])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone", re.compile(r"(?:\+55\s?\d{2}|\(\d{2}\))\s?9?\d{4}-?\d{4}")),
)


@dataclass(frozen=True)
class MaskPolicy:
    keep_keys: frozenset[str]
    scrub_keys: frozenset[str]


DEFAULT_POLICY = MaskPolicy(
    keep_keys=frozenset(
        {
            "step", "attempt", "steps", "attempts", "max_steps", "max_attempts", "model", "prompt_version",
            "prompt_tokens", "completion_tokens", "finish_reason", "cost", "currency", "prices_as_of",
            "cost_complete", "llm_calls", "calls_without_cost", "tool_error", "retry_feedback", "outcome", "name",
        }  # fmt: skip
    ),
    scrub_keys=frozenset({"user", "system", "content", "tool_calls", "arguments", "result", "facts", "error"}),
)


def scrub_text(text: str) -> str:
    for label, pattern in PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


def _scrub(value: object) -> object:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in cast("Sequence[object]", value)]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in cast("Mapping[str, object]", value).items()}
    return value


def mask_span(span: Span, policy: MaskPolicy = DEFAULT_POLICY) -> Span:
    attributes: dict[str, object] = {}
    for key, value in span.attributes.items():
        if key in policy.keep_keys:
            attributes[key] = value
        elif key in policy.scrub_keys:
            attributes[key] = _scrub(value)
        else:
            attributes[key] = f"[masked:{type(value).__name__}]"
    # `error` do próprio span carrega a mensagem da exceção, que pode trazer dado.
    error = scrub_text(span.error) if span.error is not None else None
    return replace(span, attributes=attributes, error=error)


class MaskingSink:
    """Embrulha outro sink: o que chega nele já está mascarado. O trace original não é alterado."""

    def __init__(self, inner: TraceSink, policy: MaskPolicy = DEFAULT_POLICY) -> None:
        self.inner: TraceSink = inner
        self.policy: MaskPolicy = policy

    def write(self, trace: Trace) -> None:
        self.inner.write(Trace(trace.trace_id, [mask_span(s, self.policy) for s in trace.spans]))
