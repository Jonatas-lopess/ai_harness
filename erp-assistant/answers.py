"""Pergunta sob demanda do ERP: o prompt e o leitor de números são do pack; o protocolo `STATUS:` é do harness."""

from harness.answers import STATUS_PROTOCOL, QuestionResult
from harness.answers import answer_question as _answer_question
from harness.agent import ChatClient
from harness.tools import ToolRegistry

from erp_numbers import ERP_NUMBERS

PROMPT_VERSION = "ask-v1"

SYSTEM_PROMPT = (
    "Você ajuda a equipe de um ERP. Use as tools para obter fatos; nunca invente números. "
    + STATUS_PROTOCOL
    + "Previsões e projeções NÃO são fornecidas por nenhuma tool: nesse caso, "
    + "`insufficient_data`. Não estime, não projete e não dê palpite."
)


def answer_question[C](
    client: ChatClient,
    registry: ToolRegistry[C],
    ctx: C,
    question: str,
    *,
    model: str,
    max_steps: int,
) -> QuestionResult:
    return _answer_question(
        client, registry, ctx, question, system=SYSTEM_PROMPT, reader=ERP_NUMBERS, model=model, max_steps=max_steps
    )
