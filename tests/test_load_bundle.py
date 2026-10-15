"""LoadBundle against in-memory ports: what a connector's full snapshot does to the registry."""

from __future__ import annotations

import pytest
from fakes import MemoryBlobStore, MemoryLedger, MemoryOverrides, MemoryRegistry, MemoryReviewQueue
from metamorph_contract import Bundle
from platform_samples import document, unresolved, write_bundle

from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import BundleAlreadyLoaded
from metamorph_platform.domain.loading import ReviewKind


@pytest.fixture
def ports():
    return MemoryLedger(), MemoryRegistry(), MemoryBlobStore(), MemoryReviewQueue(), MemoryOverrides()


def load(ports, directory):
    return LoadBundle(*ports).run(Bundle(directory), uri=str(directory))


def test_a_first_load_stores_documents_and_their_blobs(tmp_path, ports) -> None:
    ledger, registry, blobs, _, _ = ports

    report = load(ports, write_bundle(tmp_path / "b1", [document()]))

    assert (report.new, report.changed, report.unchanged) == (1, 0, 0)
    assert report.changed_documents == {"ojk:pojk:2014:5"}
    assert len(blobs.blobs) == 2  # the PDF and the text
    assert ledger.bundles[report.bundle_id]["state"] == "loaded"


def test_loading_the_same_snapshot_again_changes_nothing(tmp_path, ports) -> None:
    load(ports, write_bundle(tmp_path / "b1", [document()]))
    writes = ports[2].writes

    report = load(ports, write_bundle(tmp_path / "b2", [document()], run_id="run-2"))

    assert (report.new, report.changed, report.unchanged) == (0, 0, 1)
    assert report.changed_documents == set()
    assert ports[2].writes == writes


def test_a_changed_document_is_saved_again(tmp_path, ports) -> None:
    load(ports, write_bundle(tmp_path / "b1", [document()]))

    report = load(ports, write_bundle(tmp_path / "b2", [document(title="Judul yang dikoreksi")], run_id="run-2"))

    assert (report.new, report.changed) == (0, 1)


def test_the_same_connector_run_is_never_loaded_twice(tmp_path, ports) -> None:
    directory = write_bundle(tmp_path / "b1", [document()])
    load(ports, directory)

    with pytest.raises(BundleAlreadyLoaded):
        load(ports, directory)


def test_a_document_absent_from_a_full_snapshot_is_marked_missing(tmp_path, ports) -> None:
    load(ports, write_bundle(tmp_path / "b1", [document("regalert:a"), document("regalert:b")]))

    report = load(ports, write_bundle(tmp_path / "b2", [document("regalert:a")], run_id="run-2"))

    assert report.missing == 1
    assert ports[1].records[("ojk", "regalert:b")]["missing"] is True


def test_an_unidentified_document_loads_and_waits_for_a_person(tmp_path, ports) -> None:
    report = load(ports, write_bundle(tmp_path / "b1", [unresolved()]))

    assert report.new == 1 and report.to_review == 1
    kind, subject = ports[3].open[0]
    assert kind is ReviewKind.UNRESOLVED_ID and subject["document_id"].startswith("unresolved:ojk:")


def test_a_broken_line_is_quarantined_and_the_rest_still_loads(tmp_path, ports) -> None:
    ledger, _, _, reviews, _ = ports

    report = load(ports, write_bundle(tmp_path / "b1", [document()], extra_lines=['{"contract_version": "2.0"}']))

    assert (report.new, report.quarantined) == (1, 1)
    assert ledger.quarantined[0]["line"] == 2 and ledger.quarantined[0]["source_id"] is None
    assert (ReviewKind.QUARANTINE, {"bundle_id": report.bundle_id, "line": 2}) in reviews.open


def test_a_failure_mid_load_marks_the_bundle_failed(tmp_path, ports) -> None:
    ledger, registry, _, _, _ = ports

    def broken_save(*args, **kwargs):
        raise RuntimeError("database went away")

    registry.save = broken_save
    with pytest.raises(RuntimeError):
        load(ports, write_bundle(tmp_path / "b1", [document()]))

    assert ledger.bundles[1]["state"] == "failed"


def test_a_record_a_curator_identified_loads_under_the_assigned_id(tmp_path, ports) -> None:
    registry, reviews = ports[1], ports[3]
    registry.assignments[("ojk", "regalert:0f2aa739")] = "ojk:pojk:2014:6"

    report = load(ports, write_bundle(tmp_path / "b1", [unresolved()]))

    saved = registry.records[("ojk", "regalert:0f2aa739")]["document"]
    assert saved.document.id == "ojk:pojk:2014:6"
    assert report.to_review == 0 and reviews.open == []


def test_a_source_change_under_a_correction_raises_a_conflict(tmp_path, ports) -> None:
    from metamorph_platform.domain.curation import ActiveOverride

    overrides = ports[4]
    load(ports, write_bundle(tmp_path / "b1", [document()]))
    sample_title = document().document.title
    overrides.active_by_document["ojk:pojk:2014:5"] = [ActiveOverride(3, "title", "Koreksi Kurator", sample_title)]

    load(ports, write_bundle(tmp_path / "b2", [document(title="Judul baru dari sumber")], run_id="run-2"))

    assert overrides.raised == [(3, "Judul baru dari sumber")]
    assert (ReviewKind.CONFLICT, {"override_id": 3}) in ports[3].open


def test_a_manual_upload_leaves_the_other_manual_documents_alone(tmp_path, ports) -> None:
    load(ports, write_bundle(tmp_path / "b1", [document(), document("regalert:other")]))

    report = LoadBundle(*ports).run(
        Bundle(write_bundle(tmp_path / "b2", [document()], run_id="run-2")), uri="x", full_snapshot=False
    )

    assert report.missing == 0
