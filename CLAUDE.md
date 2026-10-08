# CLAUDE.md

`Guia de Estudo Harness de IA para ERP e Legal.md` (Portuguese) is the source of truth. Read the relevant section before doing real work; this file only holds rules that are not in it. Project overview and status: `README.md`. ERP setup, commands, file map: `erp-assistant/README.md`. Per-step study notes: `erp-assistant/NOTES.md`.

## Where to look in the guide

| Need | Section |
| --- | --- |
| Non-negotiable design rules | "Princípios de design" |
| Harness vs pack split, `DomainPack`, `run_job` | "Arquitetura" |
| Phases, "ready" criteria, study questions | "Roadmap por fases" |
| ERP and Legal tools, schemas, risk comparison | "Packs ERP e Legal" |
| Golden set groups, check priority, `NumbersGrounded` | "Avaliações (evals)" |
| Threats, `ai_insights`, idempotency, LGPD | "Segurança, privacidade e integração" |
| Model/SDK upgrade ritual | "Upgrade, glossário e checklist" |

## Rules that outlive the guide

- Golden rules: ERP, code computes and the LLM explains. Legal, the system of record sets every date and the LLM only summarizes, with `source_ref` (never computes or infers a deadline).
- Build order is fixed: ERP pack, then extract `ai-harness` (phase 5), then Legal against the extracted harness (phase 6). If Legal forces a harness change, ERP logic leaked into it: fix the boundary, not the harness.
- Phases are sequential. Don't advance past a phase's "ready" criterion. Don't invent build/lint/test commands: record real ones in `erp-assistant/README.md`.
- Real data: synthetic/public only during study. Real customer data to a model API needs a confirmed contract, retention and LGPD basis first.
- LLM provider is Groq, behind the `LLMClient` protocol; `groq_client.py` is the only file that knows the SDK.

## Testing conventions

- CI never calls an LLM: free, deterministic, no secrets. Real-provider tests are marked `integration`, run by hand before merging a prompt/model/SDK change, and at least once per step (fake clients don't prove provider behavior).
- Unit tests must not depend on the machine: no `.env`, no exported variables, no Docker. Check by running without `.env` and with `env -u DATABASE_URL -u GROQ_API_KEY`.
- Assert the cause, not just the type: `raises(..., match="field")`. A test that passes for the wrong reason is worse than none.
- A new eval or validator is proven by mutation: disable the rule, confirm the suite goes red, restore.
- `basedpyright` stays at 0 errors and 0 warnings.

## How to work with the study author

The author is new to Python (knows JS/TS) and asked for speed: the assistant writes code, tests and notes; the author predicts and reviews.

1. Concept with a minimal example, then the author predicts behavior (usually 2 questions).
2. Assistant implements within the step's scope only (no retry/cost/tracing ahead of time) and runs tests.
3. Walkthrough of code and decisions; explain Python as deltas from JS/TS.
4. Author answers 3 review questions ("já visto" is a valid answer; note gaps in the answers).
5. At least one real provider call.
6. Assistant writes the step's entry in `erp-assistant/NOTES.md` (honest: what broke, what is unverified, mistakes), then commits.

One phase, one new concept per session. Don't edit files the author is mid-edit on without saying so; flag problems in their edits instead. Decisions the author makes (labels, policies) go in `NOTES.md` so they aren't reopened.

## Agent skills

- Issue tracker: local markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.
- Domain docs: single context, `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
