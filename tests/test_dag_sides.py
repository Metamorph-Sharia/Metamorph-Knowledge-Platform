"""Which Airflow builds which DAG: collection on the collection host, processing on AWS (ADR 0001), without Airflow."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from metamorph_pipeline.sides import SETTING, Side, builds_here, side_from

DAGS = Path(__file__).parent.parent / "dags"


def test_the_setting_names_each_side() -> None:
    assert side_from("collection") is Side.COLLECTION
    assert side_from("processing") is Side.PROCESSING


@pytest.mark.parametrize("value", [None, "", "both", "Collection"])
def test_a_missing_or_unknown_side_fails_naming_the_setting_and_its_two_values(value) -> None:
    with pytest.raises(RuntimeError) as failure:
        side_from(value)
    message = str(failure.value)
    assert "METAMORPH_SIDE" in message and "collection" in message and "processing" in message


def test_a_dag_builds_only_on_its_own_side(monkeypatch) -> None:
    monkeypatch.setenv(SETTING, "collection")
    assert builds_here(Side.COLLECTION)
    assert not builds_here(Side.PROCESSING)
    monkeypatch.setenv(SETTING, "processing")
    assert builds_here(Side.PROCESSING)
    assert not builds_here(Side.COLLECTION)


def test_building_a_dag_without_the_setting_fails(monkeypatch) -> None:
    monkeypatch.delenv(SETTING, raising=False)
    with pytest.raises(RuntimeError, match="METAMORPH_SIDE"):
        builds_here(Side.COLLECTION)


def declared_sides() -> dict[str, str]:
    """Each DAG module's top-level `SIDE = Side.X`, read from its source: the modules need Airflow to import."""
    sides = {}
    for module in sorted(DAGS.glob("*.py")):
        for statement in ast.parse(module.read_text()).body:
            if isinstance(statement, ast.Assign) and [t.id for t in statement.targets] == ["SIDE"]:
                sides[module.stem] = ast.unparse(statement.value)
    return sides


def test_every_dag_module_declares_its_side() -> None:
    assert sorted(declared_sides()) == sorted(module.stem for module in DAGS.glob("*.py"))


def test_collection_loads_the_ingest_dags_and_the_backup_and_processing_the_rest() -> None:
    sides = declared_sides()
    assert {module for module, side in sides.items() if side == "Side.COLLECTION"} == {"ingest", "backup"}
    assert {module for module, side in sides.items() if side == "Side.PROCESSING"} == {
        "load_bundles", "registry_build", "market_publish", "market_index", "regulation_index",
    }  # fmt: skip
