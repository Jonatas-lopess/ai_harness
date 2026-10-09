from datetime import date
from decimal import Decimal

from closing import ClosingFacts
from erp_numbers import ERP_NUMBERS
from harness.masking import MaskingSink, mask_span
from harness.tracing import MemorySink, Span, trace
from harness.validators import ungrounded_in
from refill_job import RefillFacts


def make_span(**attributes: object) -> Span:
    return Span("t", "s", None, "x", "now", attributes=dict(attributes))


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
        assert ungrounded_in(str(scrubbed), facts, ERP_NUMBERS) == []


def test_every_attribute_the_code_emits_is_classified() -> None:
    # Allowlist falha fechado: atributo novo some do trace até alguém classificar. Este teste torna esse esquecimento
    # barulhento (vermelho) em vez de silencioso (trace sem o campo).
    from evals.clients import ScriptedChat, call_tool, final
    from evals.refusal import fake_ctx, fake_registry
    from harness.agent import run_agent
    from harness.pricing import costed_span
    from refill_job import explain
    from tests.test_refill_job import FACTS, ScriptedClient, ok

    inner = MemorySink()
    with trace("run", MaskingSink(inner)):
        with costed_span("job", model="m", prompt_version="v1"):
            _ = explain(ScriptedClient(ok("Repor 999."), ok("Repor 250.")), FACTS, model="m")
            chat = ScriptedChat(call_tool("sales_total"), final("ok"))
            _ = run_agent(chat, fake_registry(), fake_ctx(), model="m", system="s", user="u", max_steps=3)

    # Os parâmetros do provedor vêm do `groq_client`, que os fakes acima não exercitam: emitir um span à mão com eles.
    with trace("run", MaskingSink(inner)):
        from harness.providers.groq import _record_request  # pyright: ignore[reportPrivateUsage]
        from harness.tracing import span

        with span("llm_call"):
            _record_request(256)

    leaked = {
        f"{s.name}.{k}": v
        for t in inner.traces
        for s in t.spans
        for k, v in s.attributes.items()
        if isinstance(v, str) and v.startswith("[masked:")
    }
    assert leaked == {}, f"atributos sem classificação em DEFAULT_POLICY: {sorted(leaked)}"
