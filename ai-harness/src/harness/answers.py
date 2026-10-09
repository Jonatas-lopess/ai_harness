"""Pergunta sob demanda: o agente responde com `STATUS:` + texto e o código aplica as regras de recusa.

O campo `status` dá ao modelo uma saída legítima ("não sei") e ao código algo em que ramificar;
NÃO garante que o modelo escolha certo. Por isso o código confere o que dá para conferir sem LLM:
resposta sem evidência de tool, número sem origem, formato inválido.
"""

import re
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from harness.agent import AgentResult, ChatClient, run_agent
from harness.tools import ToolError, ToolRegistry
from harness.validators import TokenReader, ungrounded_tokens

# O formato que `judge` sabe ler. O prompt do pack tem que conter este texto (ou dizer o mesmo): se divergirem,
# toda resposta do modelo vira "rejected". O resto do prompt (domínio, tom, idioma) é do pack.
STATUS_PROTOCOL = (
    "Sua resposta final tem sempre este formato: a primeira linha é `STATUS: answered` ou "
    "`STATUS: insufficient_data`, e a partir da segunda linha vai a resposta em português. "
    "Use `answered` apenas quando as tools devolveram o que a pergunta pede, citando só valores "
    "delas. Use `insufficient_data` quando nenhuma tool fornece o que foi pedido, e explique o que "
    "falta. "
)

Status = Literal["answered", "insufficient_data", "rejected"]

_HEADER = re.compile(r"\A\s*STATUS:[ \t]*(\S+)[ \t]*\n(.*)\Z", re.DOTALL | re.IGNORECASE)


class Answer(BaseModel):
    """O que o MODELO devolve na resposta final (já separado do cabeçalho)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_data"]
    text: str


@dataclass(frozen=True)
class QuestionResult:
    status: Status  # "rejected" = a resposta do modelo reprovou nas regras do código
    text: str | None  # None quando rejeitada: texto reprovado não sai
    reason: str | None  # por que foi rejeitada
    agent: AgentResult


def _parse(raw: str) -> Answer | str:
    """Answer, ou o motivo da rejeição. Cabeçalho `STATUS:` na primeira linha, texto no resto."""
    match = _HEADER.match(raw)
    if match is None:
        return "missing 'STATUS:' header line"
    try:
        answer = Answer(status=match.group(1).lower(), text=match.group(2).strip())  # pyright: ignore[reportArgumentType]
    except ValidationError:
        return f"unknown status '{match.group(1)}'"
    if not answer.text:
        return "empty answer text"
    return answer


def judge(result: AgentResult, reader: TokenReader) -> QuestionResult:
    """Regras determinísticas sobre a resposta final; não chama modelo."""
    parsed = _parse(result.text)
    if isinstance(parsed, str):
        return QuestionResult("rejected", None, parsed, result)
    stray = ungrounded_tokens(parsed.text, result.tool_calls, reader)
    if stray:
        return QuestionResult("rejected", None, f"numbers not present in tool results: {stray}", result)
    if parsed.status == "answered":
        evidence = any(not isinstance(r.result, ToolError) for r in result.tool_calls)
        if not evidence:
            return QuestionResult("rejected", None, "answered without any successful tool call", result)
    return QuestionResult(parsed.status, parsed.text, None, result)


def answer_question[C](
    client: ChatClient,
    registry: ToolRegistry[C],
    ctx: C,
    question: str,
    *,
    system: str,
    reader: TokenReader,
    model: str,
    max_steps: int,
) -> QuestionResult:
    result = run_agent(
        client,
        registry,
        ctx,
        model=model,
        system=system,
        user=question,
        max_steps=max_steps,
    )
    return judge(result, reader)
