"""The AWS stacks' layers (deploy/aws): the core stands alone; ingestion, and the development-only access in dev/,
plug into the core's exports only, and nothing depends on dev/, so deleting it removes every public way in."""

from __future__ import annotations

import re
from pathlib import Path

AWS = Path(__file__).parents[1] / "deploy/aws"
CORE = sorted(AWS.glob("*.yaml"))
INGESTION = sorted((AWS / "ingestion").glob("*.yaml"))
DEVELOPMENT = sorted((AWS / "dev").glob("*.yaml"))


def exports(stacks: list[Path]) -> set[str]:
    return {name for stack in stacks for name in re.findall(r"Export: \{Name: ([a-z-]+)\}", stack.read_text())}


def imports(stacks: list[Path]) -> set[str]:
    return {name for stack in stacks for name in re.findall(r"ImportValue ([a-z-]+)", stack.read_text())}


def test_the_core_deploys_without_the_ingestion_layer() -> None:
    assert imports(CORE) <= exports(CORE)


def test_the_ingestion_layer_needs_nothing_but_the_core_and_itself() -> None:
    assert imports(INGESTION) <= exports(CORE) | exports(INGESTION)


def test_the_two_layers_never_export_the_same_name() -> None:
    assert not exports(CORE) & exports(INGESTION)


def test_development_access_needs_nothing_but_the_core() -> None:
    assert DEVELOPMENT
    assert imports(DEVELOPMENT) <= exports(CORE)


def test_nothing_depends_on_development_access() -> None:
    assert not exports(DEVELOPMENT) & (imports(CORE) | imports(INGESTION))
