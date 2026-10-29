"""LoadMarketBundle against in-memory ports: what a market connector's full snapshot does to the market store."""

from __future__ import annotations

import hashlib
import json

import pytest
from fakes import MemoryBlobStore, MemoryLedger, MemoryMarket, MemoryReviewQueue
from market_platform_samples import (
    RELEASE_BODY,
    licensed,
    release_record,
    report_record,
    series_record,
    write_market_bundle,
    write_release_bundle,
    write_report_bundle,
    write_series_bundle,
)
from metamorph_market import Bundle, Snapshot

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


def test_series_from_a_known_source_load_with_their_answers(tmp_path, ports) -> None:
    _, market, blobs, _ = ports
    records = [series_record("BU_Syariah_PosisiKeuangan", "110001010100", "Kas", {"2025-12": 1.0, "2026-01": 2.0})]

    report = load(ports, write_series_bundle(tmp_path / "b1", records))

    assert (report.new, report.quarantined) == (1, 0)
    assert len(blobs.blobs) == 2  # one answer per year
    assert market.records[("ojk-stats", records[0].source.source_id)]["record"] == records[0]


def test_series_from_a_source_the_platform_does_not_know_wait_in_quarantine(tmp_path, ports) -> None:
    ledger, _, _, reviews = ports
    unknown = MemoryMarket(registers={"ojk:lpbbti"}, sources=set())
    records = [series_record("BU_Syariah_PosisiKeuangan", "110001010100", "Kas", {"2026-01": 2.0})]

    report = LoadMarketBundle(ledger, unknown, ports[2], reviews).run(
        Bundle(write_series_bundle(tmp_path / "b1", records)), uri="b1"
    )

    assert report.quarantined == 1
    (quarantined,) = ledger.quarantined
    assert quarantined["problems"] == ["series.dataset: 'ojk:portal' is not a statistics source the platform knows"]


def test_a_bundle_of_whole_datasets_leaves_the_datasets_it_does_not_carry(tmp_path, ports) -> None:
    kas = series_record("Cube_A", "1", "Kas", {"2026-01": 1.0})
    giro = series_record("Cube_A", "2", "Giro", {"2026-01": 2.0})
    other = series_record("Cube_B", "1", "Kas", {"2026-01": 3.0})
    load(ports, write_series_bundle(tmp_path / "b1", [kas, giro, other]))

    report = load(ports, write_series_bundle(tmp_path / "b2", [kas], "run-2", snapshot=Snapshot.DATASETS))

    records = ports[1].records
    assert report.missing == 1
    assert records[("ojk-stats", giro.source.source_id)]["missing"]  # gone from Cube_A, which the bundle carries
    assert not records[("ojk-stats", other.source.source_id)]["missing"]  # Cube_B: not in the bundle, untouched


def test_a_report_keeps_its_pdf_and_its_text(tmp_path, ports) -> None:
    _, market, blobs, _ = ports
    text = "<!-- page 1 -->\nKeuangan syariah tumbuh."

    report = load(ports, write_report_bundle(tmp_path / "r1", {"ojk:lpksi:2025": text}))

    record = report_record(text)
    assert (report.new, report.quarantined) == (1, 0)
    assert set(blobs.blobs) == {record.text.file, record.files[0].sha256}
    assert set(market.records[("reports", "ojk:lpksi:2025")]["files"]) == {record.text.file, record.files[0].sha256}


def test_a_report_no_longer_sent_goes_missing(tmp_path, ports) -> None:
    two_editions = {"ojk:lpksi:2024": "<!-- page 1 -->\nA", "ojk:lpksi:2025": "<!-- page 1 -->\nB"}
    load(ports, write_report_bundle(tmp_path / "r1", two_editions))

    newest = {"ojk:lpksi:2025": two_editions["ojk:lpksi:2025"]}
    report = load(ports, write_report_bundle(tmp_path / "r2", newest, "run-2"))

    assert (report.unchanged, report.missing) == (1, 1)



def test_a_release_keeps_its_body_and_belongs_to_no_register(tmp_path, ports) -> None:
    _, market, blobs, _ = ports
    record = release_record("SIARAN PERS\n\nOJK mencabut izin usaha.")

    report = load(ports, write_release_bundle(tmp_path / "s1", [record]))

    body = hashlib.sha256(RELEASE_BODY).hexdigest()
    assert (report.new, report.quarantined) == (1, 0)
    assert set(blobs.blobs) == {body}
    assert set(market.records[("reports", record.source.source_id)]["files"]) == {body}
