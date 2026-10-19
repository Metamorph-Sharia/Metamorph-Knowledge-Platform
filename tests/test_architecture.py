"""The dependency rule, enforced: source-code dependencies point inward only.

    domain  →  application  →  adapters  →  entry points (cli, wiring, config, dags)

Inner rings import only the standard library, the contract package and rings further in.
Adapted from BPK-Source-Connector/tests/test_architecture.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "metamorph_platform"
CONTRACT = "metamorph_contract"

INNER_RINGS = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "application", "adapters"},
}
MAY_USE_THIRD_PARTY = {"adapters"}  # and the entry points


def ring_of(path: Path) -> str | None:
    first = path.relative_to(PACKAGE).parts[0]
    return first if first in INNER_RINGS else None


def imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def violations() -> list[str]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        ring = ring_of(path)
        if ring is None:
            continue
        for module in sorted(imported_modules(path)):
            top = module.split(".")[0]
            if top == "metamorph_platform":
                target = module.split(".")[1] if "." in module else ""
                if target not in INNER_RINGS[ring]:
                    found.append(f"{path.relative_to(PACKAGE)} ({ring}) imports {module}")
            elif top not in sys.stdlib_module_names | {CONTRACT, "__future__"} and ring not in MAY_USE_THIRD_PARTY:
                found.append(f"{path.relative_to(PACKAGE)} ({ring}) imports third-party {module}")
    return found


def test_dependencies_point_inward_only() -> None:
    assert violations() == []


def test_the_guard_catches_an_outward_import(tmp_path, monkeypatch) -> None:
    """The rule above is only worth something if it fails on a violation."""
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "bad.py").write_text("import psycopg\nfrom metamorph_platform.adapters import postgres\n")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", tmp_path)

    assert violations() == [
        "domain/bad.py (domain) imports metamorph_platform.adapters",
        "domain/bad.py (domain) imports third-party psycopg",
    ]
