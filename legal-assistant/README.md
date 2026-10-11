# legal-assistant

Legal pack of the ai-harness study project: a daily digest of deadlines and docket movements per matter. Rule: **the system of record sets every date; the LLM only summarizes**, and never computes or infers a deadline. Every item of the digest carries a `source_ref` (e.g. `deadline:17`) that the **code** attaches from the row it read, never the model.

Own database, credentials and deploy; shares only code with the ERP pack, via `ai-harness`. Synthetic data only.

No job yet: this is the skeleton (schema, seed with traps, settings). The jobs come step by step (see `../.scratch/phase-6-legal/notes.md` and the study notes).

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
| Seed tests (need the Postgres above) | `uv run pytest -m integration` |
| Typecheck (must stay at 0 errors, 0 warnings) | `uv run basedpyright` |

CI runs only the unit tests and the typecheck, like the ERP.

## The seed ("today" is `as_of = 2026-03-10`)

| Matter | Responsible | Trap |
| --- | --- | --- |
| 1 | ana | deadline in 3 days; a docket event whose text gives orders to the model (prompt injection, phase 8) |
| 2 | ana | deadline already overdue and still open |
| 3 | ana | no docket event at all ("not enough data") |
| 4 | bruno | someone else's matter: ana must never see it (permissions) |
