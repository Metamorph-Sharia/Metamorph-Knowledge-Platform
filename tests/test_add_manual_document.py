"""A curator adds a document no connector holds: it travels the same road as every bundle."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fakes import (
    MemoryBlobStore,
    MemoryCurationActions,
    MemoryLedger,
    MemoryOverrides,
    MemoryRegistry,
    MemoryReviewQueue,
)

from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.domain.manual import InvalidManualDocument, ManualDocument

ANI = Curator("ani", "Ani Rahma")
ENTRY = ManualDocument(
    document_id="dsnmui:fatwa:170",
    citation="Fatwa DSN-MUI No. 170/DSN-MUI/X/2026",
    title="Pembiayaan Rumah Syariah",
    kind="fatwa",
    status="in_force",
    language="id",
    source_url="https://dsnmui.or.id/kategori/fatwa/",
    effective_on="2026-10-01",
    file_name="fatwa-170.pdf",
    file_bytes=b"%PDF-1.7 fatwa 170",
    media_type="application/pdf",
    text="FATWA DEWAN SYARIAH NASIONAL\nNomor 170/DSN-MUI/X/2026",
    reason="Diterbitkan setelah sync mingguan",
)


@pytest.fixture
def world():
    registry, actions = MemoryRegistry(), MemoryCurationActions()
    load = LoadBundle(MemoryLedger(), registry, MemoryBlobStore(), MemoryReviewQueue(), MemoryOverrides())
    return AddManualDocument(load, actions, known=lambda document_id: False), registry, actions


def test_a_manual_document_is_loaded_as_a_manual_source_record_and_audited(world) -> None:
    add, registry, actions = world

    document_id = add.run(ANI, ENTRY)

    record = registry.records[("manual", "manual:dsnmui:fatwa:170")]["document"]
    assert document_id == "dsnmui:fatwa:170"
    assert (record.document.family, record.document.number, record.document.year) == ("fatwa", "170", None)
    assert record.files[0].source_url == "https://dsnmui.or.id/kategori/fatwa/"
    assert [t.of_file for t in record.texts] == [record.files[0].sha256]
    assert actions.calls[0][1:3] == ("add_document", {"document_id": "dsnmui:fatwa:170"})


def test_a_manual_document_without_text_still_carries_its_file(world) -> None:
    add, registry, _ = world

    add.run(ANI, replace(ENTRY, text=""))

    assert registry.records[("manual", "manual:dsnmui:fatwa:170")]["document"].texts == ()


def test_every_problem_with_the_form_is_reported_by_field(world) -> None:
    add, registry, actions = world
    broken = replace(ENTRY, document_id="fatwa 170", title=" ", status="valid", effective_on="1/10/2026", source_url="")

    with pytest.raises(InvalidManualDocument) as refused:
        add.run(ANI, broken)

    assert set(refused.value.problems) == {"document_id", "title", "status", "effective_on", "source_url"}
    assert registry.records == {} and actions.calls == []


def test_an_id_already_held_is_refused(world) -> None:
    _, registry, actions = world
    add = AddManualDocument(world[0].load, actions, known=lambda document_id: True)

    with pytest.raises(CurationRefused, match="already"):
        add.run(ANI, ENTRY)
