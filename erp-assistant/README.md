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
| Typecheck (must stay at 0 errors, 0 warnings) | `uv run basedpyright` |

CI (`.github/workflows/ci.yml` at the repo root) runs the unit tests, the simulated evals and the typecheck. It never calls an LLM: that keeps it free, deterministic and secret-free. Real calls run by hand before merging a prompt, model or SDK change.

## Layout

| File | Role |
| --- | --- |
| `extract.py`, `groq_client.py` | `LLMClient` protocol, retry, usage; `groq_client.py` is the only file that knows the Groq SDK |
| `pricing.py`, `prices.json` | versioned prices, cost per call and per job (`costed_span`) recorded in the trace |
| `tools.py`, `erp_tools.py` | read-only tool registry and the ERP tools |
| `agent.py` | agent loop with step budget |
| `replenishment.py`, `refill_job.py` | reorder detection and quantity (SQL and Python), rationale via LLM |
| `closing.py`, `closing_job.py` | daily sales summary |
| `narrate.py` | generic "facts to validated text" loop shared by both jobs |
| `validators.py` | numbers in the text must come from the facts, attached to the right field |
| `answers.py` | on-demand questions with `STATUS: answered / insufficient_data` and refusal rules |
| `tracing.py` | trace = tree of spans with a request ID, `Protocol` sinks (memory, JSONL); `agent.py` and `narrate.py` emit spans (no-op without an active trace) |
| `masking.py` | `MaskingSink`: allowlist of trace attributes, PII patterns scrubbed from free text, rest masked |
| `judge.py` | LLM-as-judge for fidelity (different model family than the generator) |
| `evals/` | golden sets (detection, fidelity, closing, refusal, trajectory), runner, judge calibration |
| `NOTES.md` | per-step study notes in Portuguese: what was learned, what broke |

## Notes on the data

Synthetic seed only. Real customer data to a model API needs a confirmed contract, retention policy and LGPD basis first.
