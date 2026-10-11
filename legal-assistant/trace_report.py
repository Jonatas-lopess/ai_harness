"""`python -m trace_report <request_id>`: o comando do harness com o arquivo de traces do Legal como padrão."""

from collections.abc import Sequence

from harness.trace_report import CorruptTraceLine, Found, Search, find_traces, render
from harness.trace_report import main as _main

from legal_traces import TRACE_PATH

__all__ = ["CorruptTraceLine", "Found", "Search", "find_traces", "main", "render"]


def main(argv: Sequence[str] | None = None) -> int:
    return _main(argv, default_file=TRACE_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
