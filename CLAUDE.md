# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`Guia de Estudo Harness de IA para ERP e Legal.md` (Portuguese) is source of truth — read it, not just this summary, before doing real work. Update this file with real build/lint/test commands once code exists; don't invent them now.

## What this project is

Shared library (**harness**) + two independent domain **packs** (ERP, Legal), built incrementally as the author learns AI engineering. Harness owns what's common: LLM calls, tool registry, budgets, output validation, tracing, evals. Each pack owns what's domain-specific: tools, prompts, schemas, validators, tests. ERP and Legal share no data, credentials, or deploy — only code.

- ERP: flags stock-replenishment needs, summarizes checkout/financial data. Nightly stock job, morning financial job, on-demand questions.
- Legal: surfaces case deadlines, summarizes docket movements. Daily digest, new-movement trigger, on-demand questions.
- Golden rule — ERP: code computes, LLM explains. Legal: system of record sets dates, LLM only summarizes (never computes/infers a deadline).

Full detail (tools list, risk comparison, Pydantic schemas): guide's "Packs ERP e Legal" section.

## Architecture

```
ai-harness/                 # library, versioned by tag
  harness/{runtime,llm,tools,guardrails,tracing,evals,scheduler,approvals}/
erp-assistant/              # ERP pack + deploy
  pack/{tools,schemas,policies}.py   prompts/   evals/   app.py
legal-assistant/            # Legal pack + deploy
  pack/{tools,schemas,policies}.py   prompts/   evals/   app.py
```

Each product gets its own sidecar service that imports the harness and loads its pack — own DB, credentials, model config. Host product calls the sidecar (or gets webhooks from it) and reads results from an `ai_insights` table, never raw model text.

Harness owns: LLM gateway (provider, routing, cache, retry), tool registry + MCP client with permission wrapper, agent loop with step/cost budget, `RequestContext`, guardrails/output validation, tracing/audit, eval runner, scheduler/triggers/approval queue.

Pack owns: domain read tools, versioned prompts, output schemas, domain validators/policies, golden-set eval cases, job schedule/triggers.

Core interface sketch (names will drift — check current SDK docs before implementing): guide's "Arquitetura" section, `DomainPack` protocol + `run_job`.

Build order: ERP pack first (most deterministic) → extract `ai-harness` as its own versioned package only after ERP works (phase 5) → build Legal pack against the extracted harness (phase 6). Phase 6 is the abstraction test — if Legal forces a harness change, ERP-specific logic leaked into it; fix the boundary.

## Design principles (non-negotiable)

1. Deterministic core, LLM at the edges — SQL/business rules detect and compute; LLM prioritizes, explains, summarizes.
2. Output validation — every number/date in generated text must trace to a tool result.
3. Read-only tools — assistant only reads; actions become drafts a human approves.
4. Permissions on every call — `RequestContext` (tenant, user, role) filters every tool.
5. Audit everything — prompt, tools called, results, cost, model version, request ID.
6. Budgets — step/token/cost limits per run, bounded retries.
7. Low coupling — business logic in plain Python; orchestration framework only wires pieces, so model/library swaps don't need a rewrite.

Legal extra: procedural deadlines have legal consequences — LLM never computes/infers dates, only presents what the system of record gives, with `source_ref`.

Real data: synthetic/public only during study phases. Real customer data to a model API needs confirmed contract, retention, LGPD basis first; prefer zero-retention or self-hosted for Legal.

## Roadmap (phases 0–8, sequential, don't skip)

| Phase | Deliverable |
| --- | --- |
| 0. Foundation | ERP-assistant running with `uv`, Docker Compose Postgres seed, empty tests passing |
| 1. Model call | Text in → validated Pydantic object out, cost logged, retry on invalid output |
| 2. ERP deterministic detection | Reorder job: code computes quantity, LLM writes rationale; tools read-only |
| 3. ERP validators & evals | 20–40 golden-set scenarios; CI fails on wrong number/SKU |
| 4. Observability | Every run traceable: prompt, tools, result, latency, cost |
| 5. Harness extraction | `ai-harness` extracted; ERP-assistant imports it; pack swap needs no harness edits |
| 6. Legal pack | Daily digest with `source_ref` per item; dates match system of record exactly |
| 7. Triggers & integration | Scheduled/on-demand jobs write `ai_insights`; re-run never duplicates records/cost |
| 8. Hardening & upgrade | Tenant/role filters, LGPD, prompt-injection tests, budgets; model upgrade compared via evals |

Per-phase study questions and "ready" criteria: guide's "Roadmap por fases" table. Post-phase-8 extras (optional): MCP servers, LangGraph port, RAG in Legal.

## Evals

Start in phase 3, run every change. Golden set per pack, four groups: correct detection, false alarm, fidelity (summary only cites given facts), refusal ("insufficient data" when warranted). Check priority: deterministic (numbers/dates/IDs trace to tool output, schema valid) > trajectory (right tools/order/budget) > fidelity/quality (calibrated LLM-as-judge) > refusal. Simulated model on every commit; real calls before merging prompt/model/SDK changes. Track score + cost per run.

Starter numbers-grounded validator, refine later (doesn't yet handle number formatting or legit derived calculations): guide's "Avaliações (evals)" section, `NumbersGrounded` class.

## Security & integration

Treat all LLM-ingested text (docket entries, free-text ERP fields) as untrusted — read-only tools, retrieved text never grants permission or triggers action, actions are approval-gated drafts. `RequestContext` enforced inside every tool; DB role at minimum privilege. Mask sensitive fields before logging. Per-tenant cost/step budgets. Idempotency key (task + input hash + date) so re-run never duplicates `ai_insights` rows or spend. Rollout: shadow mode → feature flag, few tenants first.

`ai_insights` columns and full threat table: guide's "Segurança, privacidade e integração" section.

## Model/SDK upgrade ritual

Branch → pin version → read release notes for harness impact → real-call eval suite on both packs → compare score/cost/latency to current → investigate regressions in traces → merge only if scores don't drop; record model + prompt version in every trace.

## How to work with the study author

They implement each phase themselves; assistant explains, questions, reviews — never writes the implementation for them. Per phase: concept explanation with minimal example → author predicts behavior → author implements → assistant reviews design/risks/alternatives without rewriting → author writes an eval/unit test → notes in a per-phase `NOTES.md`. One phase, one new concept per session; don't advance past a phase's "ready" criterion.

Ready-to-copy prompt templates for each cycle step: guide's "Como estudar com a IA" section.

## Agent skills

### Issue tracker

Issues tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
