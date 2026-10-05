from datetime import date

from pytest import mark

from agent import run_agent
from erp_tools import erp_registry
from groq_client import GroqClient
from settings import get_settings
from tools import ToolContext, connect_readonly

MODEL = "openai/gpt-oss-120b"
AS_OF = date(2026, 1, 31)

SYSTEM = (
    "Você ajuda a equipe de compras de um ERP. Use as tools para obter fatos; nunca invente números. "
    "Responda em português, citando apenas valores devolvidos pelas tools."
)


@mark.integration
def test_real_agent_calls_low_stock_and_cites_its_numbers() -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        result = run_agent(
            client,
            erp_registry(),
            ToolContext(conn=conn, as_of=AS_OF),
            model=MODEL,
            system=SYSTEM,
            user="Quais produtos precisam de reposição hoje e quanto devo pedir de cada um?",
            max_steps=settings.max_steps,
        )

    print(f"\nsteps={result.steps} usage={result.usage}")
    for record in result.tool_calls:
        print(f"tool={record.name} args={record.arguments} -> {record.result.model_dump_json()}")
    print(f"text={result.text}")

    assert "low_stock" in [r.name for r in result.tool_calls]
    # 250 e 240 vêm do cálculo em código (seed); o modelo só pode repeti-los.
    assert "250" in result.text
    assert "240" in result.text
