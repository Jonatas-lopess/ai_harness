from datetime import date
from decimal import Decimal
from pathlib import Path

from pytest import mark

from closing import ClosingFacts
from masking import MaskingSink, MaskPolicy, mask_span, scrub_text
from refill_job import RefillFacts
from tracing import JsonlSink, MemorySink, Span, span, trace
from validators import ungrounded_in

CPF = "123.456.789-09"


def make_span(**attributes: object) -> Span:
    return Span("t", "s", None, "x", "now", attributes=dict(attributes))


def test_key_outside_the_allowlist_is_masked_with_its_type() -> None:
    # O cenário da pergunta 1: atributo novo, adicionado sem pensar em privacidade.
    masked = mask_span(make_span(customer_email="ana@example.com", customer_id=42))

    assert masked.attributes == {"customer_email": "[masked:str]", "customer_id": "[masked:int]"}


def test_kept_keys_pass_untouched() -> None:
    attrs = {"model": "m", "prompt_tokens": 10, "cost": Decimal("0.1"), "tool_error": False, "cost_complete": True}

    assert mask_span(make_span(**attrs)).attributes == attrs


@mark.parametrize(
    ("raw", "expected"),
    [
        (f"cliente {CPF} comprou", "cliente [cpf] comprou"),
        ("cpf 12345678909 fim", "cpf [cpf] fim"),
        ("cnpj 12.345.678/0001-95", "cnpj [cnpj]"),
        ("cnpj 12345678000195", "cnpj [cnpj]"),
        ("escreva para ana.souza+x@example.com.br", "escreva para [email]"),
        ("ligue (11) 91234-5678 ou +55 11 91234-5678", "ligue [phone] ou [phone]"),
    ],
)
def test_patterns_are_replaced_in_scrubbed_text(raw: str, expected: str) -> None:
    assert scrub_text(raw) == expected


def test_scrub_keeps_numbers_that_are_not_personal_ids() -> None:
    text = "Faturamento de R$ 10950.00 com 465 unidades, pedido 1234567890, lote 123456789012"

    assert scrub_text(text) == text  # 10 e 12 dígitos soltos não são CPF nem CNPJ


def test_scrub_reaches_inside_nested_values() -> None:
    masked = mask_span(
        make_span(
            tool_calls=[{"id": "c1", "name": "x", "arguments": f'{{"doc": "{CPF}"}}'}],
            result=f'{{"owner": "{CPF}"}}',
        )
    )

    assert CPF not in str(masked.attributes)
    assert "[cpf]" in str(masked.attributes["tool_calls"])


def test_error_message_of_the_span_is_scrubbed() -> None:
    s = make_span()
    s.status, s.error = "error", f"ValueError: cpf {CPF} inválido"

    masked = mask_span(s)

    assert masked.error == "ValueError: cpf [cpf] inválido"
    assert masked.status == "error"


def test_masking_does_not_mutate_the_original_span() -> None:
    s = make_span(customer_email="ana@example.com", user=CPF)

    _ = mask_span(s)

    assert s.attributes == {"customer_email": "ana@example.com", "user": CPF}


def test_scrubbing_the_real_facts_keeps_them_grounded() -> None:
    # Critério da fase: mascarar não pode tirar do trace o que a checagem de fundamento precisa.
    refill = RefillFacts(
        product_id=1, name="Parafuso", on_hand=3, open_po_qty=0, reorder_point=40, suggested_qty=250
    )
    closing = ClosingFacts(day=date(2026, 1, 20), revenue=Decimal("10950.00"), units=465, top_product="received-po")
    for facts in (refill, closing):
        original = facts.model_dump_json()
        scrubbed = mask_span(make_span(facts=original)).attributes["facts"]
        assert scrubbed == original
        assert ungrounded_in(str(scrubbed), facts) == []


def test_custom_policy_decides_what_passes() -> None:
    policy = MaskPolicy(keep_keys=frozenset({"a"}), scrub_keys=frozenset())

    assert mask_span(make_span(a=1, b=2), policy).attributes == {"a": 1, "b": "[masked:int]"}


def test_masking_sink_hands_only_masked_traces_to_the_inner_sink() -> None:
    inner = MemorySink()
    with trace("job", MaskingSink(inner), request_id="r1"):
        with span("llm_call", model="m", prompt_tokens=5, user=f"meu cpf é {CPF}", customer="Ana") as s:
            s.set(content="ok")

    [t] = inner.traces
    assert t.trace_id == "r1"  # o request_id não é mascarado: é a chave para achar o trace
    _, call = t.spans
    assert call.attributes == {
        "model": "m",
        "prompt_tokens": 5,
        "user": "meu cpf é [cpf]",
        "customer": "[masked:str]",
        "content": "ok",
    }


def test_the_jsonl_file_never_contains_the_personal_data(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    with trace("job", MaskingSink(JsonlSink(path))):
        with span("llm_call", user=f"cpf {CPF} e ana@example.com", secret_note="Ana Souza"):
            pass

    text = path.read_text(encoding="utf-8")
    assert CPF not in text and "ana@example.com" not in text and "Ana Souza" not in text
    assert "[cpf]" in text and "[email]" in text


def test_every_attribute_the_code_emits_is_classified() -> None:
    # Allowlist falha fechado: atributo novo some do trace até alguém classificar. Este teste torna esse esquecimento
    # barulhento (vermelho) em vez de silencioso (trace sem o campo).
    from agent import ToolCall, run_agent
    from pricing import costed_span
    from refill_job import explain
    from tests.test_agent import ScriptedChat, _answer, _call, _ctx, _registry  # pyright: ignore[reportPrivateUsage]
    from tests.test_refill_job import FACTS, ScriptedClient, ok

    inner = MemorySink()
    with trace("run", MaskingSink(inner)):
        with costed_span("job", model="m", prompt_version="v1"):
            _ = explain(ScriptedClient(ok("Repor 999."), ok("Repor 250.")), FACTS, model="m")
            chat = ScriptedChat(_call(ToolCall("c1", "echo", '{"n": 1}')), _answer("ok"))
            _ = run_agent(chat, _registry(), _ctx(), model="m", system="s", user="u", max_steps=3)

    leaked = {
        f"{s.name}.{k}": v
        for t in inner.traces
        for s in t.spans
        for k, v in s.attributes.items()
        if isinstance(v, str) and v.startswith("[masked:")
    }
    assert leaked == {}, f"atributos sem classificação em DEFAULT_POLICY: {sorted(leaked)}"
