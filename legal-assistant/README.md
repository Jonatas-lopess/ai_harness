# legal-assistant

Legal pack of the ai-harness study project: a daily digest of deadlines and docket movements per matter. Rule: **the system of record sets every date; the LLM only summarizes**, and never computes or infers a deadline. Every item of the digest carries a `source_ref` (e.g. `deadline:17`) that the **code** attaches from the row it read, never the model.

Own database, credentials and deploy; shares only code with the ERP pack, via `ai-harness`. Synthetic data only.

The digest job covers deadlines and docket events (one `narrate` call per row, sequential; a matter with no event in the window gets a fixed line written by the code, no model call); the on-demand questions and tracing come step by step (study notes: `../erp-assistant/NOTES.md`, "Fase 6").

## Setup

Needs [`uv`](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env        # fill GROQ_API_KEY (must start with gsk_)
docker compose up -d --wait # Postgres 17 on port 5433 (the ERP uses 5432), schema and seed from initdb/
uv sync
```

## Commands

| What | Command |
| --- | --- |
| Unit tests (no network, no Docker) | `uv run pytest -m "not integration"` |
| Tests that need the Postgres above (seed, tools, job with a fake model) | `uv run pytest -m integration --deselect tests/test_legal_digest_integration.py` |
| Real Groq call (uses free-tier quota; run only when verifying new model behavior) | `uv run pytest tests/test_legal_digest_integration.py -s` |
| Rebuild the story of one run from its request ID (`--full` adds prompt and results) | `uv run python -m trace_report <request_id> [--file traces.jsonl] [--full]` |
| Typecheck (must stay at 0 errors, 0 warnings; uses this folder's own `pyrightconfig.json`, not the repo root's) | `uv run basedpyright` |

CI runs only the unit tests and the typecheck, like the ERP.

## Layout

| File | Role |
| --- | --- |
| `legal_context.py` | `LegalContext(conn, as_of, user_id)` (no default for the user) and `connect_readonly` |
| `legal_tools.py` | `upcoming_deadlines(days)` (`overdue` and `upcoming` apart) and `recent_events(days)` (events plus `quiet_matters`), both filtered by the context's user; `source_ref` built by code |
| `legal_tokens.py` | what counts as a value in Legal text: dates (`date`), case numbers (`str`), integers; composed by the pack |
| `legal_digest.py` | `DeadlineFacts` (no ids), `EventFacts` (the event text is untrusted third-party data), `build_digest` (one `narrate` per row; a rejected sentence degrades to the record data plus a warning), `run_digest_job` |
| `evals/` | `fidelity` golden set (simulated model, runs in CI: `python -m evals`); by hand with the real model: `evals.real_digest` (first-attempt acceptance) and `evals.real_injection` (does the model obey an order hidden in a docket event?) |
| `legal_prices.py`, `prices.json` | the Legal's own price table |
| `legal_traces.py`, `trace_report.py` | where the Legal writes traces (`traces/traces.jsonl`, git-ignored, never the ERP's file) and the command that reads them |

## Traces and client data

Wrap a job in `trace("digest", legal_trace_sink(), request_id=...)`. The trace holds what explains a sentence: the tool calls and results, one `digest_item <source_ref>` span per row with the facts sent to the model, the model's answer, retries and cost. That includes client data (case numbers, the text of docket events), so the sink is always the masking one: CPF, CNPJ, e-mail and phone patterns are replaced, unknown attributes are masked. **Person names are not masked** (known limit, tested). With synthetic data this is fine; with real data, define retention and access first and a per-origin mask policy (phase 8).

## The seed ("today" is `as_of = 2026-03-10`)

| Matter | Responsible | Trap |
| --- | --- | --- |
| 1 | ana | deadline in 3 days; a docket event whose text gives orders to the model (prompt injection, phase 8) |
| 2 | ana | deadline already overdue and still open |
| 3 | ana | no docket event at all ("not enough data") |
| 4 | bruno | someone else's matter: ana must never see it (permissions) |
