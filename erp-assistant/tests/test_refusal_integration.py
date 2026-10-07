from datetime import date

from pytest import mark

from answers import answer_question
from erp_tools import erp_registry
from groq_client import GroqClient
from settings import get_settings
from tools import ToolContext, connect_readonly

MODEL = "openai/gpt-oss-120b"
AS_OF = date(2026, 1, 31)

pytestmark = mark.integration

# (pergunta, status esperado). Nenhuma tool fornece previsão, preço de concorrente ou tendência.
QUESTIONS = [
    ("Qual será a venda do mês que vem?", "insufficient_data"),
    ("Qual o preço que o concorrente pratica no parafuso?", "insufficient_data"),
    ("Quais produtos precisam de reposição hoje e quanto devo pedir de cada um?", "answered"),
    ("Qual o prazo de entrega do fornecedor 1?", "answered"),
]


@mark.parametrize(("question", "expected"), QUESTIONS)
def test_real_model_refuses_or_answers(question: str, expected: str) -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        result = answer_question(
            client,
            erp_registry(),
            ToolContext(conn=conn, as_of=AS_OF),
            question,
            model=MODEL,
            max_steps=settings.max_steps,
        )

    names = [r.name for r in result.agent.tool_calls]
    print(f"\nQ={question}\nstatus={result.status} reason={result.reason} tools={names}")
    print(f"raw={result.agent.text}")
    assert result.status == expected
