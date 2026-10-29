"""A market bundle: written as a full snapshot, read back by a loader that never trusts it blindly."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from market_samples import build_record, build_release, build_report, build_series
from metamorph_market import (
    Bundle,
    BundleWriter,
    ContractViolation,
    FileRef,
    LicensedEntityRecord,
    LicenseKind,
    Snapshot,
    UnloadableBundle,
    to_json,
)

PDF = b"%PDF-1.7 a register edition"


def write(directory: Path, *records: LicensedEntityRecord, connector: str = "ojk-register") -> None:
    with BundleWriter(directory, connector=connector, connector_version="0.1.0", run_id="run-1") as bundle:
        sha = bundle.put_blob(PDF)
        for record in records:
            bundle.add(_pointing_at(record, sha))


def _pointing_at(record: LicensedEntityRecord, sha: str) -> LicensedEntityRecord:
    files = tuple(replace(file, sha256=sha) for file in record.files)
    listings = tuple(replace(listing, file=sha) for listing in record.listings)
    return replace(record, files=files, listings=listings)


def test_a_written_bundle_reads_back_whole(tmp_path: Path) -> None:
    record = build_record()
    write(tmp_path, record)

    bundle = Bundle(tmp_path)
    (entry,) = list(bundle.entries())

    assert entry.is_valid
    assert entry.record.entity == record.entity
    assert bundle.manifest.records == 1
    assert bundle.manifest.blobs == 1
    assert bundle.blob_path(entry.record.files[0].sha256).read_bytes() == PDF


def test_a_failed_export_writes_no_manifest(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, connector="ojk-register", connector_version="0.1.0", run_id="r")
    with pytest.raises(RuntimeError), writer:
        raise RuntimeError("the export crashed")

    with pytest.raises(UnloadableBundle, match="no manifest"):
        Bundle(tmp_path)


def test_a_record_must_not_reference_a_blob_left_out(tmp_path: Path) -> None:
    with pytest.raises(ContractViolation, match="was not put into this bundle"):  # noqa: SIM117
        with BundleWriter(tmp_path, connector="ojk-register", connector_version="0.1.0", run_id="r") as bundle:
            bundle.add(build_record())


def test_a_license_is_in_a_bundle_once(tmp_path: Path) -> None:
    with pytest.raises(ContractViolation, match="already in this bundle"):
        write(tmp_path, build_record(), build_record())


def test_records_come_from_the_bundles_connector(tmp_path: Path) -> None:
    with pytest.raises(ContractViolation, match="in a 'bi-register' bundle"):
        write(tmp_path, build_record(), connector="bi-register")


def test_a_broken_line_is_reported_not_raised(tmp_path: Path) -> None:
    write(tmp_path, build_record())
    records = tmp_path / "records.jsonl"
    records.write_text(records.read_text() + '{"kind": "licensed_entity"}\n', encoding="utf-8")

    entries = list(Bundle(tmp_path).entries())

    assert [entry.is_valid for entry in entries] == [True, False]
    assert entries[1].raw == '{"kind": "licensed_entity"}'


def test_a_missing_blob_makes_its_record_invalid(tmp_path: Path) -> None:
    write(tmp_path, build_record())
    for blob in (tmp_path / "blobs").rglob("*"):
        if blob.is_file():
            blob.unlink()

    (entry,) = list(Bundle(tmp_path).entries())

    assert not entry.is_valid
    assert entry.problems[0].endswith("is missing")


def test_a_manifest_of_another_contract_is_refused(tmp_path: Path) -> None:
    write(tmp_path, build_record())
    manifest = tmp_path / "manifest.json"
    data = json.loads(manifest.read_text())
    manifest.write_text(json.dumps({**data, "contract_version": "2.1"}), encoding="utf-8")

    with pytest.raises(UnloadableBundle, match="breaks the contract"):
        Bundle(tmp_path)


def test_records_round_trip_through_json() -> None:
    from metamorph_market import from_json

    record = build_record()
    assert from_json(to_json(record)) == record
    assert isinstance(from_json(to_json(record)).files[0], FileRef)
    assert isinstance(from_json(to_json(record)).entity.license.kind, LicenseKind)


def test_series_and_licenses_share_a_bundle_and_round_trip(tmp_path: Path) -> None:
    from metamorph_market import Observation, SeriesRecord, from_json

    with BundleWriter(tmp_path, connector="ojk-stats", connector_version="0.1.0", run_id="run-1") as bundle:
        sha = bundle.put_blob(b"<soap:Envelope/>")
        series = build_series()
        series = replace(
            series,
            files=tuple(replace(file, sha256=sha) for file in series.files),
            observations=tuple(replace(observation, file=sha) for observation in series.observations),
        )
        bundle.add(series)

    (entry,) = list(Bundle(tmp_path).entries())
    assert entry.is_valid
    assert isinstance(entry.record, SeriesRecord)
    assert from_json(to_json(series)) == series
    assert isinstance(entry.record.observations[0], Observation)


def test_a_quarterly_series_round_trips_with_its_frequency_unit_and_marks() -> None:
    from metamorph_market import Frequency, from_json

    series = build_series()
    series = replace(
        series,
        series=replace(series.series, industry=None, frequency=Frequency.QUARTERLY, unit="Miliar Rp"),
        observations=(replace(series.observations[0], period="2026-Q2", provisional=True),),
    )

    back = from_json(to_json(series))
    assert back == series
    assert isinstance(back.series.frequency, Frequency)


def test_a_bundle_may_carry_whole_datasets_only(tmp_path: Path) -> None:
    with BundleWriter(
        tmp_path, connector="ojk-stats", connector_version="0.1.0", run_id="run-1", snapshot=Snapshot.DATASETS
    ) as bundle:
        sha = bundle.put_blob(b"{}")
        series = build_series()
        bundle.add(
            replace(
                series,
                files=tuple(replace(file, sha256=sha) for file in series.files),
                observations=tuple(replace(observation, file=sha) for observation in series.observations),
            )
        )

    assert Bundle(tmp_path).manifest.snapshot == Snapshot.DATASETS


def test_a_bundle_is_a_full_snapshot_unless_said_otherwise(tmp_path: Path) -> None:
    write(tmp_path, build_record())
    assert Bundle(tmp_path).manifest.snapshot == Snapshot.FULL


def _report_in(bundle: BundleWriter) -> object:
    record = build_report()
    pdf, text = bundle.put_blob(b"%PDF-1.7 a report"), bundle.put_blob(b"<!-- page 1 -->\nBAB 1\n")
    return replace(
        record,
        files=tuple(replace(file, sha256=pdf) for file in record.files),
        text=replace(record.text, file=text),
    )


def test_a_report_carries_its_pdf_and_its_text_as_blobs_and_round_trips(tmp_path: Path) -> None:
    from metamorph_market import ReportRecord, TextMethod, from_json

    with BundleWriter(tmp_path, connector="reports", connector_version="0.1.0", run_id="run-1") as bundle:
        report = _report_in(bundle)
        bundle.add(report)

    (entry,) = list(Bundle(tmp_path).entries())
    assert entry.is_valid
    assert isinstance(entry.record, ReportRecord)
    assert entry.record == report == from_json(to_json(report))
    assert isinstance(entry.record.text.method, TextMethod)
    assert Bundle(tmp_path).blob_path(report.text.file).read_bytes().startswith(b"<!-- page 1 -->")


def test_a_report_must_not_reference_a_text_left_out(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, connector="reports", connector_version="0.1.0", run_id="run-1")
    with pytest.raises(ContractViolation, match="was not put into this bundle"), writer as bundle:
        report = _report_in(bundle)
        bundle.add(replace(report, text=replace(report.text, file="f" * 64)))



def test_a_release_carries_its_page_as_a_blob_and_its_text_inline(tmp_path: Path) -> None:
    from metamorph_market import ReleaseRecord, from_json

    with BundleWriter(tmp_path, connector="reports", connector_version="0.2.0", run_id="run-1") as bundle:
        record = build_release()
        page = bundle.put_blob(b'<div id="summary"><p>SIARAN PERS</p></div>')
        release = replace(record, files=tuple(replace(file, sha256=page) for file in record.files))
        bundle.add(release)

    (entry,) = list(Bundle(tmp_path).entries())
    assert entry.is_valid
    assert isinstance(entry.record, ReleaseRecord)
    assert entry.record == release == from_json(to_json(release))


def test_a_release_must_not_reference_a_page_left_out(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, connector="reports", connector_version="0.2.0", run_id="run-1")
    with pytest.raises(ContractViolation, match="was not put into this bundle"), writer as bundle:
        bundle.add(build_release())
