"""Eval REAL (à mão, usa a quota da Groq): o modelo escreve o digest do seed e medimos a aceitação de primeira.

Não roda no CI. Use ao mudar prompt, modelo ou SDK: `uv run python -m evals.real_digest --rounds 3`.
Cada rodada são 4 chamadas no mínimo (os 4 prazos da ana no seed). O que importa:
- aceitação na 1ª tentativa: quanto o prompt acerta sem o feedback do validador (tentativa extra custa token e tempo);
- avisos: itens que não passaram em `max_attempts` (saem só com os dados do registro).
"""

import argparse
import sys
from datetime import date

from harness.llm import Usage, add_usage
from harness.pricing import compute_cost
from harness.providers.groq import GroqClient

from legal_context import LegalContext, connect_readonly
from legal_digest import run_digest_job
from legal_prices import load_legal_prices
from settings import get_settings

MODEL = "openai/gpt-oss-120b"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--rounds", type=int, default=1)
    rounds: int = parser.parse_args(argv).rounds  # pyright: ignore[reportAny]

    settings = get_settings()
    client = GroqClient(settings.groq_api_key.get_secret_value())
    total = Usage(0, 0)
    attempts: list[int] = []
    warnings = 0
    with connect_readonly(settings.database_url.get_secret_value()) as conn:
        ctx = LegalContext(conn=conn, as_of=date(2026, 3, 10), user_id="ana")
        for n in range(1, rounds + 1):
            digest = run_digest_job(client, ctx, model=MODEL)
            total = add_usage(total, digest.usage)
            for item in digest.items:
                attempts.append(item.attempts)
                warnings += item.warning is not None
                print(f"round {n} {item.source_ref} attempts={item.attempts} warning={item.warning}\n  {item.sentence}")

    first_try = sum(a == 1 for a in attempts)
    price = load_legal_prices().models.get(MODEL)
    print(f"\nitems={len(attempts)} accepted-on-first-attempt={first_try}/{len(attempts)} warnings={warnings}")
    print(f"usage={total} cost_usd={compute_cost(total, price)}")
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
