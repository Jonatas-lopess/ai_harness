# ai-harness

A shared library (**harness**) plus two independent domain packs — **ERP** and **Legal** — for building AI assistants on top of business systems. Built incrementally as a learning project in AI engineering.

- **Harness**: LLM calls, tool registry, budgets, output validation, tracing, evals — everything domain-agnostic.
- **ERP pack**: flags stock-replenishment needs, summarizes checkout/financial data.
- **Legal pack**: surfaces case deadlines, summarizes docket movements.

Design principle: deterministic code computes and decides; the LLM explains and summarizes. In the Legal pack, the LLM never computes or infers a deadline — only presents what the system of record gives.

## Status

Study project, built in sequential phases (details in `CLAUDE.md`; full guide in Portuguese: `Guia de Estudo Harness de IA para ERP e Legal.md`).

| Phase | Deliverable | State |
| --- | --- | --- |
| 0. Foundation | `uv`, Docker Compose Postgres seed, tests | done |
| 1. Model call | text in, validated Pydantic object out, cost logged, retry | done |
| 2. ERP detection | reorder job: code computes quantity, LLM writes the rationale | done |
| 3. Validators and evals | golden sets, CI that fails on a wrong number, calibrated LLM judge | done |
| 4. Observability | every run traceable | done (spans, request ID, instrumented loop, cost per job, masking, `trace_report`, provider parameters and tool schemas in the trace) |
| 5. Harness extraction | `ai-harness` package, ERP imports from it | criterion met and proven by a toy pack; tag and repo split deferred (the repo becomes the harness's when split) |
| 6. Legal pack | daily digest of deadlines and docket events with `source_ref`, fidelity and refusal evals, own traces | criterion met (`legal-assistant/`); the guide's checkbox is the author's |
| 7-8 | Triggers, hardening | planned |

The ERP pack is in `erp-assistant/` and the Legal pack in `legal-assistant/` (own database, credentials and traces; they share only code, via `ai-harness`). The harness extraction (phase 5) is under way: `ai-harness/` already holds `tracing`, `tools`, `llm`, `pricing`, `agent`, `validators` and `narrate`; the rest still lives next to the ERP code and moves step by step. The Legal pack comes after, as the test that the harness is really domain-agnostic.

## Structure

```
ai-harness/           # domain-agnostic library, package `harness`; `examples/toy_pack` shows how to write a pack
erp-assistant/        # ERP pack: working code, tests, evals, notes (see its README)
docs/agents/          # issue tracker and domain-doc conventions for coding agents
.github/workflows/    # CI: unit tests, simulated evals, typecheck (no network, no secrets)
```

Planned for `ai-harness/` (today: `tracing`, `tools`, `llm`, `pricing`, `agent`, `validators`, `narrate`, `masking`, `evals` and more).

```
ai-harness/           # library, versioned by tag
  harness/{runtime,llm,tools,guardrails,tracing,evals,scheduler,approvals}/
legal-assistant/      # Legal pack + deploy
```

ERP and Legal share no data, credentials, or deploy, only code, via the harness.

## Quick start

See `erp-assistant/README.md`. Needs `uv` and Docker; the LLM provider is Groq (free tier), so tests that call it are marked `integration` and stay out of CI.
