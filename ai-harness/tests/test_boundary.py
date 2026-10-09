import ast
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "harness"
# O harness só pode depender da biblioteca padrão, do pydantic e de si mesmo.
ALLOWED = set(sys.stdlib_module_names) | {"pydantic", "harness"}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_harness_imports_nothing_from_a_pack_or_a_provider():
    offenders = {
        str(p.relative_to(SRC)): sorted(_imported_roots(p) - ALLOWED)
        for p in SRC.rglob("*.py")
        if _imported_roots(p) - ALLOWED
    }

    assert offenders == {}, f"harness imports outside its boundary: {offenders}"
