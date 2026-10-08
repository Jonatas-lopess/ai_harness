import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from evals import closing, detection, fidelity, refusal


class _Named(Protocol):
    @property
    def name(self) -> str: ...


class Scored(Protocol):
    @property
    def case(self) -> _Named: ...

    @property
    def passed(self) -> bool: ...


Suite = Callable[[], Sequence[Scored]]

# Simulated model only: no network, no Docker, no cost. Safe to run on every commit.
SUITES: dict[str, Suite] = {
    "detection": detection.run,
    "fidelity": fidelity.run,
    "closing": closing.run,
    "refusal": refusal.run,
}


def run_all(suites: dict[str, Suite] = SUITES) -> dict[str, Sequence[Scored]]:
    return {name: run() for name, run in suites.items()}


def main() -> int:
    outcome = run_all()
    failed = 0
    for name, results in outcome.items():
        bad = [r for r in results if not r.passed]
        failed += len(bad)
        print(f"{name}: {len(results) - len(bad)}/{len(results)}")
        for r in bad:
            print(f"  FAIL {name}/{r.case.name}")
    total = sum(len(rs) for rs in outcome.values())
    print(f"total: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
