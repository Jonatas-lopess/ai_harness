"""`python -m evals`: as suítes do Legal rodadas pelo runner do harness (`harness.evals`)."""

import sys
from collections.abc import Sequence
from pathlib import Path

from harness.evals import Scored, Suite
from harness.evals import main as _main
from harness.evals import run_all as _run_all

from evals import fidelity, refusal

HISTORY_PATH = Path(__file__).with_name("history.jsonl")

# Modelo simulado: sem rede, sem Docker, sem custo. Seguro de rodar a cada commit.
SUITES: dict[str, Suite] = {
    "fidelity": fidelity.run,
    "refusal": refusal.run,
}


def run_all() -> dict[str, Sequence[Scored]]:
    return _run_all(SUITES)


def main(argv: Sequence[str] = ()) -> int:
    return _main(argv, suites=SUITES, history_path=HISTORY_PATH)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
