"""LoadMarketBundle against in-memory ports: what a market connector's full snapshot does to the market store."""

from __future__ import annotations

import json

import pytest
from fakes import MemoryBlobStore, MemoryLedger, MemoryMarket, MemoryReviewQueue
from market_platform_samples import licensed, write_market_bundle
from metamorph_market import Bundle

from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.domain.loading import ReviewKind

JAN, FEB = "2021-01-31", "2021-02-28"


@pytest.fixture
def ports():
    return MemoryLedger(), MemoryMarket(), MemoryBlobStore(), MemoryReviewQueue()


def load(ports, directory):
    return LoadMarketBundle(*ports).run(Bundle(directory), uri=str(directory))


def test_a_first_load_keeps_each_record_and_its_editions_files(tmp_path, ports) -> None:
    ledger, market, blobs, _ = ports
    records = [licensed("KEP-1/D.05/2021", JAN, FEB), licensed("KEP-2/D.05/2021", FEB, legal_name="PT Two")]

    report = load(ports, write_market_bundle(tmp_path / "b1", records))

    assert (report.new, report.changed, report.unchanged, report.quarantined) == (2, 0, 0, 0)
    assert len(blobs.blobs) == 2  # January's PDF and February's, each once
    assert set(market.records[("ojk-register", "KEP-1/D.05/2021")]["files"]) == {
        file.sha256 for file in records[0].files
    }
    assert ledger.bundles[report.bundle_id]["state"] == "loaded"


def test_the_same_snapshot_again_changes_nothing(tmp_path, ports) -> None:
    records = [licensed("KEP-1/D.05/2021", JAN)]
    load(ports, write_market_bundle(tmp_path / "b1", records))
    writes = ports[2].writes

    report = load(ports, write_market_bundle(tmp_path / "b2", records, run_id="run-2"))

    assert (report.new, report.changed, report.unchanged) == (0, 0, 1)
    assert ports[2].writes == writes


def test_a_record_listed_in_a_new_edition_is_saved_again(tmp_path, ports) -> None:
    load(ports, write_market_bundle(tmp_path / "b1", [licensed("KEP-1/D.05/2021", JAN)]))

    report = load(ports, write_market_bundle(tmp_path / "b2", [licensed("KEP-1/D.05/2021", JAN, FEB)], "run-2"))

    assert report.changed == 1


def test_a_broken_line_is_quarantined_for_review(tmp_path, ports) -> None:
    ledger, _, _, reviews = ports
    directory = write_market_bundle(tmp_path / "b1", [licensed("KEP-1/D.05/2021", JAN)])
    records = directory / "records.jsonl"
    records.write_text(records.read_text() + json.dumps({"kind": "licensed_entity"}) + "\n", encoding="utf-8")

    report = load(ports, directory)

    assert (report.new, report.quarantined) == (1, 1)
    assert ledger.quarantined[0]["line"] == 2
    assert reviews.open == [(ReviewKind.QUARANTINE, {"bundle_id": report.bundle_id, "line": 2})]


def test_a_record_on_a_register_the_platform_does_not_know_is_quarantined(tmp_path, ports) -> None:
    ledger = ports[0]
    unknown = licensed("KEP-9/D.05/2021", JAN, register="ojk:insurance")

    report = load(ports, write_market_bundle(tmp_path / "b1", [unknown]))

    assert (report.new, report.quarantined) == (0, 1)
    assert ledger.quarantined[0]["problems"] == [
        "entity.register: 'ojk:insurance' is not a register the platform knows"
    ]


def test_a_record_the_snapshot_no_longer_has_is_marked_missing(tmp_path, ports) -> None:
    both = [licensed("KEP-1/D.05/2021", JAN), licensed("KEP-2/D.05/2021", JAN)]
    load(ports, write_market_bundle(tmp_path / "b1", both))

    report = load(ports, write_market_bundle(tmp_path / "b2", [licensed("KEP-1/D.05/2021", JAN)], "run-2"))

    assert report.missing == 1
    assert ports[1].records[("ojk-register", "KEP-2/D.05/2021")]["missing"]
