# legal-assistant

Legal pack of the ai-harness study project: a daily digest of deadlines and docket movements per matter. Rule: **the system of record sets every date; the LLM only summarizes**, and never computes or infers a deadline. Every item of the digest carries a `source_ref` (e.g. `deadline:17`) that the **code** attaches from the row it read, never the model.

Own database, credentials and deploy; shares only code with the ERP pack, via `ai-harness`. Synthetic data only.

The digest job covers deadlines (one `narrate` call per row, sequential); docket events, the on-demand questions and tracing come step by step (study notes: `../erp-assistant/NOTES.md`, "Fase 6").

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
| Typecheck (must stay at 0 errors, 0 warnings; uses this folder's own `pyrightconfig.json`, not the repo root's) | `uv run basedpyright` |

CI runs only the unit tests and the typecheck, like the ERP.

## Layout

| File | Role |
| --- | --- |
| `legal_context.py` | `LegalContext(conn, as_of, user_id)` (no default for the user) and `connect_readonly` |
| `legal_tools.py` | `upcoming_deadlines(days)`: `overdue` and `upcoming` apart, filtered by the context's user; `source_ref` built by code |
| `legal_tokens.py` | what counts as a value in Legal text: dates (`date`), case numbers (`str`), integers; composed by the pack |
| `legal_digest.py` | `DeadlineFacts` (no ids), `build_digest` (one `narrate` per row; a rejected sentence degrades to the record data plus a warning), `run_digest_job` |
| `legal_prices.py`, `prices.json` | the Legal's own price table |

## The seed ("today" is `as_of = 2026-03-10`)

| Matter | Responsible | Trap |
| --- | --- | --- |
| 1 | ana | deadline in 3 days; a docket event whose text gives orders to the model (prompt injection, phase 8) |
| 2 | ana | deadline already overdue and still open |
| 3 | ana | no docket event at all ("not enough data") |
| 4 | bruno | someone else's matter: ana must never see it (permissions) |
