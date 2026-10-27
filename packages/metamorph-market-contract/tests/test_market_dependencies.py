"""Every market connector depends on this package, so what it imports is a deliberate, short list."""

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "metamorph_market"
THIRD_PARTY = {"jsonschema"}  # validates the JSON Schemas, which are the formal contract


def imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_the_market_contract_imports_only_the_standard_library_jsonschema_and_itself() -> None:
    allowed = set(sys.stdlib_module_names) | THIRD_PARTY | {"metamorph_market", "__future__"}
    outside = {
        f"{path.name}: {module}"
        for path in PACKAGE.rglob("*.py")
        for module in imported_modules(path)
        if module not in allowed
    }
    assert outside == set()
