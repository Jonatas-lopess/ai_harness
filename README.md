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
| 5. Harness extraction | `ai-harness` package, ERP imports from it | in progress (done: `tracing`, `tools`, `llm`, `pricing`) |
| 6-8 | Legal pack, triggers, hardening | planned |

Only the ERP pack exists so far, in `erp-assistant/`. The harness extraction (phase 5) is under way: `ai-harness/` already holds `tracing`, `tools`, `llm` and `pricing`; the rest still lives next to the ERP code and moves step by step. The Legal pack comes after, as the test that the harness is really domain-agnostic.

## Structure

```
ai-harness/           # domain-agnostic library, package `harness` (see below)
erp-assistant/        # ERP pack: working code, tests, evals, notes (see its README)
docs/agents/          # issue tracker and domain-doc conventions for coding agents
.github/workflows/    # CI: unit tests, simulated evals, typecheck (no network, no secrets)
```

Planned for `ai-harness/` (today: `tracing`, `tools`, `llm`, `pricing`); not created yet: `legal-assistant/`.

```
ai-harness/           # library, versioned by tag
  harness/{runtime,llm,tools,guardrails,tracing,evals,scheduler,approvals}/
legal-assistant/      # Legal pack + deploy
```

ERP and Legal share no data, credentials, or deploy, only code, via the harness.

## Quick start

See `erp-assistant/README.md`. Needs `uv` and Docker; the LLM provider is Groq (free tier), so tests that call it are marked `integration` and stay out of CI.
