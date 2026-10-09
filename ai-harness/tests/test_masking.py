from decimal import Decimal
from pathlib import Path

from pytest import mark

from harness.masking import MaskingSink, MaskPolicy, mask_span, scrub_text
from harness.tracing import JsonlSink, MemorySink, Span, span, trace

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
