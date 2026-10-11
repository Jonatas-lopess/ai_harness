"""Pergunta sob demanda do Legal: prompt e leitor são do pack; o protocolo `STATUS:` e as regras de recusa são do harness.

Regra extra do pack: tool que devolve **vazio** não é evidência. O `judge` do harness conta qualquer tool sem erro; no
Legal, "nenhum prazo encontrado" respondido como se houvesse prazo é o erro caro, então `answered` sem nenhum registro
nos resultados é rejeitado.
"""

from collections.abc import Sequence
from typing import cast

from harness.agent import ChatClient, ToolCallRecord
from harness.answers import STATUS_PROTOCOL, QuestionResult
from harness.answers import answer_question as _answer_question
from harness.tools import ToolRegistry

from harness.validators import Token, TokenReader

from legal_tokens import LEGAL_TOKENS, CaseNumberReader

PROMPT_VERSION = "ask-v1"

SYSTEM_PROMPT = (
    "Você ajuda um advogado a consultar prazos e movimentações dos processos dele. Use as tools para obter os"
    + " fatos; nunca invente datas, números de processo ou prazos. "
    + STATUS_PROTOCOL
    + "Toda data vem do sistema de registro, exatamente como a tool devolveu: nunca calcule, estime, conte dias "
    + "nem deduza um prazo (por exemplo, a partir da data de uma sentença ou de uma regra processual), e não dê "
    + "conselho jurídico. Se nenhuma tool devolver o prazo ou a movimentação pedidos para aquele processo, responda "
    + "`insufficient_data` e diga o que falta; não responda com o prazo de outro processo ou de outro tipo."
)


class _EchoedCaseNumbersAllowed:
    """Leitor da resposta que não confere o número de processo que o próprio usuário digitou na pergunta.

    Recusar "o processo X não tem prazo" repete X, que não está nas tools justamente porque não há registro dele. É eco de
    identificação, não afirmação. Só o número de processo: uma DATA da pergunta continua exigindo o registro (senão
    "vence em 20/03, certo?" seria "confirmado" pela própria pergunta).
    """

    def __init__(self, base: TokenReader, question: str) -> None:
        self._base: TokenReader = base
        self._echoed: frozenset[str] = frozenset(t.text for t in CaseNumberReader().find(question))

    def find(self, text: str) -> Sequence[Token]:
        return [t for t in self._base.find(text) if t.text not in self._echoed]


def has_records(calls: Sequence[ToolCallRecord]) -> bool:
    """Alguma tool devolveu pelo menos um registro (lista não vazia em qualquer campo)? Erro e vazio contam como não."""
    for call in calls:
        dumped = cast(dict[str, object], call.result.model_dump())
        if any(isinstance(value, list) and len(cast(list[object], value)) > 0 for value in dumped.values()):
            return True
    return False


def answer_question[C](
    client: ChatClient,
    registry: ToolRegistry[C],
    ctx: C,
    question: str,
    *,
    model: str,
    max_steps: int,
) -> QuestionResult:
    result = _answer_question(
        client,
        registry,
        ctx,
        question,
        system=SYSTEM_PROMPT,
        reader=_EchoedCaseNumbersAllowed(LEGAL_TOKENS, question),
        model=model,
        max_steps=max_steps,
    )
    if result.status == "answered" and not has_records(result.agent.tool_calls):
        return QuestionResult("rejected", None, "answered but the tools returned no records", result.agent)
    return result
