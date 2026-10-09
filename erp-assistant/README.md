# erp-assistant

ERP pack of the ai-harness study project: flags stock-replenishment needs and summarizes the day's sales. Rule: **code computes, the LLM explains**. Every number in generated text must trace back to a tool result or a computed fact.

No runnable app yet: `main.py` is a placeholder. The jobs are library functions exercised by tests and evals.

## Setup

Needs [`uv`](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env        # fill GROQ_API_KEY (must start with gsk_)
docker compose up -d --wait # Postgres 17 with schema and seed from initdb/
uv sync
```

## Commands

| What | Command |
| --- | --- |
| Unit tests (no network, no Docker) | `uv run pytest -m "not integration"` |
| All tests (Postgres and real Groq calls; uses free-tier quota) | `uv run pytest` |
| Simulated evals, 5 golden sets | `uv run python -m evals` |
| Same, appending score to `evals/history.jsonl` | `uv run python -m evals --record` |
| Calibrate the LLM judge (real Groq calls) | `uv run python -m evals.judge_calibration` |
| Rebuild the story of one run from its request ID (`--full` adds prompt and results) | `uv run python -m trace_report <request_id> [--file traces.jsonl] [--full]` |
| Typecheck (must stay at 0 errors, 0 warnings) | `uv run basedpyright` |
| Harness tests, core only (adapter tests are skipped) | inside `ai-harness/`: `uv sync && uv run pytest` |
| Harness tests with the Groq adapter, and typecheck | inside `ai-harness/`: `uv sync --extra groq && uv run pytest && uv run basedpyright` |

CI (`.github/workflows/ci.yml` at the repo root) runs the unit tests, the simulated evals and the typecheck. It never calls an LLM: that keeps it free, deterministic and secret-free. Real calls run by hand before merging a prompt, model or SDK change.

## Layout

| File | Role |
| --- | --- |
| `extract.py` | phase 1 exercise (`StockMessage` extraction with retry); no production job uses it |
| `harness.llm` (in `ai-harness/`) | `LLMClient` protocol, `Completion`, `Usage`, errors, `parse_completion`, `with_feedback` |
| `harness.providers.groq` (in `ai-harness/`, extra `[groq]`) | the only file that knows the Groq SDK |
| `erp_prices.py`, `prices.json` | the ERP's versioned prices; `load_erp_prices()` reads the file on every job run (no global cache) |
| `harness.pricing` (in `ai-harness/`) | cost per call and per job (`costed_span(prices=...)`) recorded in the trace; the price table comes from the pack |
| `erp_context.py` | `ErpContext` (DB connection + `as_of`) and `connect_readonly`: what the harness hands to every ERP tool |
| `erp_tools.py` | the ERP tools; the generic registry (`harness.tools`) lives in `ai-harness/` |
| `harness.agent` (in `ai-harness/`) | agent loop with step budget, generic in the tool context |
| `replenishment.py`, `refill_job.py` | reorder detection and quantity (SQL and Python), rationale via LLM |
| `closing.py`, `closing_job.py` | daily sales summary |
| `harness.narrate` (in `ai-harness/`) | generic "facts to validated text" loop shared by both jobs |
| `harness.validators` (in `ai-harness/`) | numbers in the text must come from the facts, attached to the right field; reads numbers through a `TokenReader` the pack provides |
| `erp_numbers.py` | `ERP_NUMBERS`: what counts as a number in ERP text (pt-BR/en separators, ids like `A12`) |
| `answers.py` | the ERP prompt and number reader for on-demand questions; the `STATUS:` protocol and refusal rules are `harness.answers` |
| `harness.tracing` (in `ai-harness/`) | trace = tree of spans with a request ID, `Protocol` sinks (memory, JSONL); `harness.agent` and `harness.narrate` emit spans (no-op without an active trace) |
| `harness.masking` (in `ai-harness/`) | `MaskingSink`: allowlist of trace attributes, PII patterns scrubbed from free text, rest masked; `production_sink(path)` is the way to build the JSONL sink |
| `erp_traces.py` | where the ERP writes traces (`traces/traces.jsonl`, git-ignored) |
| `trace_report.py` | the `harness.trace_report` command with the ERP trace file as default: span tree, totals and cost for one `request_id`; last trace wins with a warning, a corrupt line aborts |
| `harness.judge` (in `ai-harness/`) | LLM-as-judge for fidelity (different model family than the generator) |
| `evals/` | the ERP golden sets (detection, fidelity, closing, refusal, trajectory), the labeled judge examples, and the wiring to the harness runner (`python -m evals`) |
| `harness.evals`, `harness.calibration`, `harness.testing` (in `ai-harness/`) | suite runner and history, judge-calibration math, LLM test doubles (`ScriptedChat`, `FixedClient`, ...) |
| `NOTES.md` | per-step study notes in Portuguese: what was learned, what broke |

## Notes on the data

Synthetic seed only. Real customer data to a model API needs a confirmed contract, retention policy and LGPD basis first.
