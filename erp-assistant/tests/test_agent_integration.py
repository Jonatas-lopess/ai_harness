import json
from datetime import date
from pathlib import Path
from typing import cast

from pytest import CaptureFixture, mark

from agent import run_agent
from erp_tools import erp_registry
from groq_client import GroqClient
from settings import get_settings
from erp_context import ErpContext, connect_readonly
from trace_report import main
from masking import MaskingSink, production_sink
from harness.tracing import JsonlSink, trace
from validators import ungrounded_numbers

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
            ErpContext(conn=conn, as_of=AS_OF),
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


@mark.integration
def test_real_agent_text_has_no_ungrounded_numbers() -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        result = run_agent(
            client,
            erp_registry(),
            ErpContext(conn=conn, as_of=AS_OF),
            model=MODEL,
            system=SYSTEM,
            user="Quais produtos precisam de reposição hoje e quanto devo pedir de cada um? Some o total a pedir.",
            max_steps=settings.max_steps,
        )

    stray = ungrounded_numbers(result.text, result.tool_calls)
    print(f"\ntext={result.text}\nstray={stray}")
    assert stray == []


@mark.integration
def test_real_agent_trace_explains_the_run(tmp_path: Path) -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    path = tmp_path / "traces.jsonl"

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        with trace("real-agent", JsonlSink(path), request_id="real-1"):
            result = run_agent(
                client,
                erp_registry(),
                ErpContext(conn=conn, as_of=AS_OF),
                model=MODEL,
                system=SYSTEM,
                user="Quais produtos precisam de reposição hoje e quanto devo pedir de cada um?",
                max_steps=settings.max_steps,
            )

    [line] = path.read_text(encoding="utf-8").splitlines()
    recorded = cast("dict[str, object]", json.loads(line))
    spans = cast("list[dict[str, object]]", recorded["spans"])
    attrs = [cast("dict[str, object]", s["attributes"]) for s in spans]
    for s, a in zip(spans, attrs, strict=True):
        print(f"{s['name']!s:9} {s['duration_ms']!s:>22}ms {s['status']} {list(a)}")

    assert recorded["trace_id"] == "real-1"
    llm = [a for s, a in zip(spans, attrs, strict=True) if s["name"] == "llm_call"]
    assert len(llm) == result.steps
    # O que o trace diz bate com o que a execução devolveu: é o critério "explicar a resposta pelo trace".
    assert sum(int(str(a["prompt_tokens"])) for a in llm) == result.usage.prompt_tokens
    tools = [a["name"] for s, a in zip(spans, attrs, strict=True) if s["name"] == "tool"]
    assert tools == [r.name for r in result.tool_calls]
    assert llm[-1]["content"] == result.text


@mark.integration
def test_real_masked_trace_hides_the_cpf_but_keeps_what_explains_the_run(tmp_path: Path) -> None:
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    path = tmp_path / "traces.jsonl"
    cpf = "123.456.789-09"  # sintético: o modelo recebe a pergunta como está, só o trace é mascarado

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        with trace("real-masked", MaskingSink(JsonlSink(path)), request_id="real-3"):
            result = run_agent(
                client,
                erp_registry(),
                ErpContext(conn=conn, as_of=AS_OF),
                model=MODEL,
                system=SYSTEM,
                user=f"O solicitante (CPF {cpf}) quer saber quais produtos precisam de reposição hoje e quanto pedir.",
                max_steps=settings.max_steps,
            )

    text = path.read_text(encoding="utf-8")
    print(f"\nuser no trace: {cast('dict[str, object]', json.loads(text.splitlines()[0]))['spans']!s:.200}")
    assert cpf not in text
    assert "[cpf]" in text
    recorded = cast("dict[str, object]", json.loads(text))
    spans = cast("list[dict[str, object]]", recorded["spans"])
    llm = [cast("dict[str, object]", s["attributes"]) for s in spans if s["name"] == "llm_call"]
    assert sum(int(str(a["prompt_tokens"])) for a in llm) == result.usage.prompt_tokens  # custo segue legível
    assert llm[-1]["content"] == result.text  # o texto final segue legível (sem dado pessoal nele)


@mark.integration
def test_real_run_can_be_explained_end_to_end_from_the_request_id(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Critério de pronto da fase 4: da resposta ao que o modelo recebeu, só pelo `request_id`."""
    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    path = tmp_path / "traces.jsonl"

    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        with trace("real-agent", production_sink(path), request_id="real-4"):
            result = run_agent(
                client,
                erp_registry(),
                ErpContext(conn=conn, as_of=AS_OF),
                model=MODEL,
                system=SYSTEM,
                user="Quais produtos precisam de reposição hoje e quanto devo pedir de cada um?",
                max_steps=settings.max_steps,
            )

    _ = capsys.readouterr()
    assert main(["real-4", "--file", str(path), "--full"]) == 0
    story = capsys.readouterr().out
    with capsys.disabled():
        print(f"\n{story}")

    assert story.startswith("request_id=real-4")
    assert "(completo)" in story
    assert f"{result.usage.prompt_tokens}→{result.usage.completion_tokens} tokens" in story
    # As três lacunas do passo 2 que o passo 6 fecha:
    assert "temperature: 0" in story and "reasoning_effort: low" in story  # o que o provedor recebeu
    assert "max_completion_tokens: 1024" in story
    assert "low_stock" in story and "tools:" in story  # os schemas que o modelo viu
    assert result.text.splitlines()[0] in story  # a resposta final
