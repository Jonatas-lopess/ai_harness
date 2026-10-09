"""Runner de evals: roda as suítes que o PACK registra, imprime, devolve o código de saída e guarda o histórico.

Os golden sets são do pack; aqui só existe o que independe de domínio: o contrato `Scored` e a contagem.
Usa modelo simulado (sem rede, sem custo): seguro de rodar a cada commit.
"""

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Protocol


class _Named(Protocol):
    @property
    def name(self) -> str: ...


class Scored(Protocol):
    @property
    def case(self) -> _Named: ...

    @property
    def passed(self) -> bool: ...


Suite = Callable[[], Sequence[Scored]]


def run_all(suites: Mapping[str, Suite]) -> dict[str, Sequence[Scored]]:
    return {name: run() for name, run in suites.items()}


def history_entry(
    outcome: Mapping[str, Sequence[Scored]], *, commit: str, day: date
) -> dict[str, object]:
    """Uma linha do histórico: score por suíte + custo. Compara execuções (modelo, prompt, commit)."""
    return {
        "date": day.isoformat(),
        "commit": commit,
        "mode": "simulated",
        "scores": {n: [sum(r.passed for r in rs), len(rs)] for n, rs in outcome.items()},
        # Clientes simulados devolvem Usage(0, 0): o custo é zero por construção. Execução real
        # passa a preencher.
        "cost_usd": 0.0,
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def record(outcome: Mapping[str, Sequence[Scored]], path: Path) -> None:
    entry = history_entry(outcome, commit=_git_commit(), day=date.today())
    with path.open("a", encoding="utf-8") as f:
        _ = f.write(json.dumps(entry) + "\n")


def main(argv: Sequence[str], *, suites: Mapping[str, Suite], history_path: Path) -> int:
    """0 se tudo passa, 1 se algum caso falha. `--record` acrescenta uma linha a `history_path`."""
    outcome = run_all(suites)
    failed = 0
    for name, results in outcome.items():
        bad = [r for r in results if not r.passed]
        failed += len(bad)
        print(f"{name}: {len(results) - len(bad)}/{len(results)}")
        for r in bad:
            print(f"  FAIL {name}/{r.case.name}")
    total = sum(len(rs) for rs in outcome.values())
    print(f"total: {total - failed}/{total}")
    if "--record" in argv:
        record(outcome, history_path)
    return 1 if failed else 0
