"""`python -m evals`: as suítes do ERP rodadas pelo runner do harness (`harness.evals`)."""

import sys
from collections.abc import Sequence
from pathlib import Path

from evals import closing, detection, fidelity, refusal, trajectory
from harness.evals import Scored, Suite
from harness.evals import main as _main
from harness.evals import run_all as _run_all

HISTORY_PATH = Path(__file__).with_name("history.jsonl")

# Simulated model only: no network, no Docker, no cost. Safe to run on every commit.
SUITES: dict[str, Suite] = {
    "detection": detection.run,
    "fidelity": fidelity.run,
    "closing": closing.run,
    "refusal": refusal.run,
    "trajectory": trajectory.run,
}


def run_all() -> dict[str, Sequence[Scored]]:
    return _run_all(SUITES)


def main(argv: Sequence[str] = ()) -> int:
    return _main(argv, suites=SUITES, history_path=HISTORY_PATH)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
