import ast
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "harness"
# O núcleo só pode depender da biblioteca padrão, do pydantic e de si mesmo.
CORE_ALLOWED = set(sys.stdlib_module_names) | {"pydantic", "harness"}
# Cada adaptador de provedor pode, além disso, importar o SDK do seu provedor (e só ele).
PROVIDER_SDKS = {"providers/groq.py": {"groq"}}


def _imports(path: Path) -> list[str]:
    """Nomes completos dos módulos importados (`harness.providers.groq`, `pydantic`, ...)."""
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def test_harness_imports_nothing_from_a_pack_or_an_unlisted_provider() -> None:
    offenders: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        allowed = CORE_ALLOWED | PROVIDER_SDKS.get(rel, set())
        bad = sorted({n for n in _imports(path) if n.split(".")[0] not in allowed})
        if bad:
            offenders[rel] = bad

    assert offenders == {}, f"harness imports outside its boundary: {offenders}"


def test_the_core_never_imports_a_provider_adapter() -> None:
    # Sem isto, `import harness.agent` exigiria o extra `groq` instalado.
    offenders = {
        path.relative_to(SRC).as_posix(): [n for n in _imports(path) if n.startswith("harness.providers")]
        for path in SRC.rglob("*.py")
        if not path.relative_to(SRC).as_posix().startswith("providers/")
        and any(n.startswith("harness.providers") for n in _imports(path))
    }

    assert offenders == {}, f"core modules import a provider adapter: {offenders}"
