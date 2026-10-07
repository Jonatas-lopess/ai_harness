"""Clientes simulados dos evals."""

import json
from typing import Any

from extract import Completion, Usage


class FixedClient:
    """Responde sempre o mesmo texto, em todas as tentativas."""

    def __init__(self, text: str) -> None:
        self.text: str = text

    def complete(self, **_: Any) -> Completion:  # pyright: ignore[reportExplicitAny]
        return Completion(json.dumps({"rationale": self.text}), "stop", usage=Usage(0, 0))
