"""The dependency rule, enforced: source-code dependencies point inward only.

    domain  →  application  →  adapters  →  the composition root (the package's __init__)

The domain and application import only the standard library and rings further in; only adapters may import a
reader's library (httpx, pymupdf). Adapted from the platform's tests/test_architecture.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "metamorph_pdf_text"

INNER_RINGS = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "application", "adapters"},
}
MAY_USE_THIRD_PARTY = {"adapters"}


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
        ring = path.relative_to(PACKAGE).parts[0]
        if ring not in INNER_RINGS:
            continue
        for module in sorted(imported_modules(path)):
            top = module.split(".")[0]
            if top == "metamorph_pdf_text":
                target = module.split(".")[1] if "." in module else ""
                if target not in INNER_RINGS[ring]:
                    found.append(f"{path.relative_to(PACKAGE)} ({ring}) imports {module}")
            elif top not in sys.stdlib_module_names | {"__future__"} and ring not in MAY_USE_THIRD_PARTY:
                found.append(f"{path.relative_to(PACKAGE)} ({ring}) imports third-party {module}")
    return found


def test_dependencies_point_inward_only() -> None:
    assert violations() == []


def test_the_domain_is_there_to_check() -> None:
    assert any((PACKAGE / "domain").glob("*.py"))


def test_the_guard_catches_an_outward_import(tmp_path, monkeypatch) -> None:
    """The rule above is only worth something if it fails on a violation."""
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "bad.py").write_text("import httpx\nfrom metamorph_pdf_text.adapters import mineru_reader\n")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", tmp_path)

    assert violations() == [
        "domain/bad.py (domain) imports third-party httpx",
        "domain/bad.py (domain) imports metamorph_pdf_text.adapters",
    ]
