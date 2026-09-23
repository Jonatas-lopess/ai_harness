# ai-harness

A shared library (**harness**) plus two independent domain packs — **ERP** and **Legal** — for building AI assistants on top of business systems. Built incrementally as a learning project in AI engineering.

- **Harness**: LLM calls, tool registry, budgets, output validation, tracing, evals — everything domain-agnostic.
- **ERP pack**: flags stock-replenishment needs, summarizes checkout/financial data.
- **Legal pack**: surfaces case deadlines, summarizes docket movements.

Design principle: deterministic code computes and decides; the LLM explains and summarizes. In the Legal pack, the LLM never computes or infers a deadline — only presents what the system of record gives.

## Status

Early study phase. No code yet — see `CLAUDE.md` for the architecture and phased roadmap, and `Guia de Estudo Harness de IA para ERP e Legal.md` for the full (Portuguese) source of truth.

## Structure (planned)

```
ai-harness/                 # library, versioned by tag
  harness/{runtime,llm,tools,guardrails,tracing,evals,scheduler,approvals}/
erp-assistant/               # ERP pack + deploy
legal-assistant/              # Legal pack + deploy
```

ERP and Legal share no data, credentials, or deploy — only code, via the harness.
