# CLAUDE.md

`Guia de Estudo Harness de IA para ERP e Legal.md` (Portuguese) is the source of truth. Read the relevant section before doing real work; this file only holds rules that are not in it. Project overview and status: `README.md`. ERP setup, commands, file map: `erp-assistant/README.md`; Legal: `legal-assistant/README.md`. Per-step study notes: `erp-assistant/NOTES.md`.

## Where to look in the guide

| Need | Section |
| --- | --- |
| Why and how each design principle applies | "Princípios de design" |
| Harness vs pack split, `DomainPack`, `run_job` | "Arquitetura" |
| Phases, "ready" criteria, study questions | "Roadmap por fases" |
| ERP and Legal tools, schemas, risk comparison | "Packs ERP e Legal" |
| Golden set groups, check priority, `NumbersGrounded` | "Avaliações (evals)" |
| Threats, `ai_insights`, idempotency, LGPD | "Segurança, privacidade e integração" |
| Model/SDK upgrade ritual | "Upgrade, glossário e checklist" |

## Design principles (non-negotiable; detail in the guide's "Princípios de design")

1. Deterministic core, LLM at the edges: SQL/business rules detect and compute; the LLM prioritizes, explains, summarizes.
2. Output validation: every number/date in generated text traces to a tool result.
3. Read-only tools: the assistant only reads; actions become drafts a human approves.
4. Permissions on every call: `RequestContext` (tenant, user, role) filters every tool.
5. Audit everything: prompt, tools called, results, cost, model version, request ID.
6. Budgets: step/token/cost limits per run, bounded retries.
7. Low coupling: business logic in plain Python; an orchestration framework only wires pieces.

## Rules that outlive the guide

- Golden rules: ERP, code computes and the LLM explains. Legal, the system of record sets every date and the LLM only summarizes, with `source_ref` (never computes or infers a deadline).
- Build order is fixed: ERP pack, then extract `ai-harness` (phase 5), then Legal against the extracted harness (phase 6). If Legal forces a harness change, ERP logic leaked into it: fix the boundary, not the harness.
- Phases are sequential. Don't advance past a phase's "ready" criterion. Don't invent build/lint/test commands: record real ones in the pack's README.
- Real data: synthetic/public only during study. Real customer data to a model API needs a confirmed contract, retention and LGPD basis first.
- LLM provider is Groq, behind the `LLMClient` protocol; `ai-harness/src/harness/providers/groq.py` (extra `[groq]`) is the only file that knows the SDK.

## Testing conventions

- CI never calls an LLM: free, deterministic, no secrets. Real-provider tests are marked `integration`, run by hand before merging a prompt/model/SDK change, and at least once per step (fake clients don't prove provider behavior).
- Unit tests must not depend on the machine: no `.env`, no exported variables, no Docker. Check by running without `.env` and with `env -u DATABASE_URL -u GROQ_API_KEY`.
- Assert the cause, not just the type: `raises(..., match="field")`. A test that passes for the wrong reason is worse than none.
- A new eval or validator is proven by mutation: disable the rule, confirm the suite goes red, restore.
- `basedpyright` stays at 0 errors and 0 warnings. Each pack that sits under a folder with a `pyrightconfig.json` needs its own: pyright uses the nearest config upward and ignores `[tool.basedpyright]` in `pyproject.toml`, so a pack without one reports "0 errors" while checking none of its code (happened to the Legal pack). After creating or moving a pack, plant a type error and confirm the count rises.

## How to work with the study author

The author is new to Python (knows JS/TS) and asked for speed: the assistant writes code, tests and notes; the author predicts and reviews.

1. Concept with a minimal example, then the author predicts behavior (usually 2 questions).
2. Assistant implements within the step's scope only (no retry/cost/tracing ahead of time) and runs tests.
3. Walkthrough of code and decisions; explain Python as deltas from JS/TS.
4. Author answers 3 review questions ("já visto" is a valid answer; note gaps in the answers).
5. At least one real provider call.
6. Assistant writes the step's entry in `erp-assistant/NOTES.md` (honest: what broke, what is unverified, mistakes), then commits.

Questions to the author (predictions and review) are about AI-engineering concepts the author must judge: grounding and validation of LLM output, deterministic core vs. LLM, silent vs. loud failure, retries and feedback, cost/latency/quota, what an eval proves, prompt injection, permissions, tracing. Domain details (formats, seed contents, edge cases) are the assistant's call: decide, state it, log it in `NOTES.md`. Ask only for decisions that are genuinely the author's (policy, trade-offs with consequences).

One phase, one new concept per session. Don't edit files the author is mid-edit on without saying so; flag problems in their edits instead. Decisions the author makes (labels, policies) go in `NOTES.md` so they aren't reopened.

## Agent skills

- Issue tracker: local markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.
- Domain docs: single context, `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
