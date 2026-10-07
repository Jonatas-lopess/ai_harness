from dataclasses import replace

from answers import answer_question, judge
from agent import AgentResult
from evals.clients import ScriptedChat, call_tool, final
from evals.refusal import CASES, FORECAST, LAST_MONTH, fake_ctx, fake_registry, run, run_case
from extract import Usage


def test_refusal_golden_set_passes() -> None:
    assert [r.case.name for r in run() if not r.passed] == []


def test_refusal_golden_set_covers_every_outcome() -> None:
    assert {c.expected for c in CASES} == {"answered", "insufficient_data", "rejected"}


def test_wrong_expectation_fails_the_case() -> None:
    refused = next(c for c in CASES if c.name == "forecast-refused")
    assert not run_case(replace(refused, expected="answered")).passed


def test_rejected_answer_never_exposes_its_text() -> None:
    result = answer_question(
        ScriptedChat(final("STATUS: answered\nVai crescer.")),
        fake_registry(),
        fake_ctx(),
        FORECAST,
        model="m",
        max_steps=3,
    )

    assert result.status == "rejected"
    assert result.text is None
    assert result.reason == "answered without any successful tool call"


def test_judge_works_on_a_finished_agent_result() -> None:
    agent = AgentResult("STATUS: insufficient_data\nSem dados.", Usage(0, 0), 1, ())

    assert judge(agent).status == "insufficient_data"


def test_known_gap_forecast_prose_after_a_real_tool_call_is_accepted() -> None:
    # Limite assumido: a evidência existe (a tool devolveu 300) e o texto não tem número novo, então
    # "deve crescer" passa. Só um juiz de fidelidade (passo 5) vê que a afirmação não vem da tool.
    result = answer_question(
        ScriptedChat(
            call_tool("sales_total"),
            final("STATUS: answered\nForam 300 e deve crescer no mês que vem."),
        ),
        fake_registry(),
        fake_ctx(),
        LAST_MONTH,
        model="m",
        max_steps=3,
    )

    assert result.status == "answered"
