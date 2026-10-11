"""Auxiliar de teste do Legal: monta a resposta do modelo no formato que `narrate` espera."""

from harness.llm import Completion, Usage

USAGE = Usage(10, 5)


def ok(text: str) -> Completion:
    return Completion(f'{{"rationale": "{text}"}}', "stop", usage=USAGE)
