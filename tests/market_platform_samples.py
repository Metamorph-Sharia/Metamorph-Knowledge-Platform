"""Market records and bundles for the platform's tests: licenses listed in given editions, each edition its PDF;
series observed in given months, each year its answer; and reports, each with its PDF and its text."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from market_samples import build_record, build_report, build_series
from metamorph_market import (
    BundleWriter,
    BusinessType,
    Dimension,
    FileRef,
    FileRole,
    Frequency,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    Observation,
    ReportRecord,
    SeriesRecord,
    Snapshot,
)

REGISTER = "ojk:lpbbti"


def edition_pdf(edition: str) -> bytes:
    return f"%PDF-1.7 the list of {edition}".encode()


def edition_sha(edition: str) -> str:
    return hashlib.sha256(edition_pdf(edition)).hexdigest()


def licensed(
    number: str,
    *editions: str,
    legal_name: str = "PT Lender",
    kind: LicenseKind = LicenseKind.LICENSE,
    business_type: BusinessType = BusinessType.CONVENTIONAL,
    register: str = REGISTER,
) -> LicensedEntityRecord:
    """A record listed in `editions` (ISO dates, oldest first) under `legal_name`."""
    record = build_record()
    key = number.lower().replace("/", "-")
    return replace(
        record,
        source=replace(record.source, source_id=number),
        entity=replace(
            record.entity,
            id=f"{register}:{key}",
            register=register,
            legal_name=legal_name,
            names=(),
            business_type=business_type,
            license=License(number=number, date=None, kind=kind),
        ),
        listings=tuple(
            Listing(edition=edition, file=edition_sha(edition), page=1, row=row, legal_name=legal_name,
                    cells={"Nama Perusahaan": legal_name})
            for row, edition in enumerate(editions, start=1)
        ),
        files=tuple(
            FileRef(sha256=edition_sha(edition), role=FileRole.REGISTER_EDITION, media_type="application/pdf",
                    source_url=f"https://ojk.go.id/{edition}.aspx", edition=edition)
            for edition in editions
        ),
        source_fields={"Nama Perusahaan": legal_name},
    )


def write_market_bundle(directory: Path, records: Sequence[LicensedEntityRecord], run_id: str = "run-1") -> Path:
    with BundleWriter(directory, connector="ojk-register", connector_version="0.2.0", run_id=run_id) as bundle:
        for edition in sorted({file.edition for record in records for file in record.files}):
            bundle.put_blob(edition_pdf(edition))
        for record in records:
            bundle.add(record)
    return directory


PORTAL = "ojk:portal"
BUS = "Bank Umum Syariah"


def answer_xml(year: str) -> bytes:
    return f"<soap:Envelope>{year}</soap:Envelope>".encode()


def answer_sha(year: str) -> str:
    return hashlib.sha256(answer_xml(year)).hexdigest()


def series_record(
    cube: str, key: str, label: str, values: dict[str, float], *, industry: str = BUS, edition: str = "2026-10-26"
) -> SeriesRecord:
    """One account of `cube`'s Posisi Keuangan: `values` by month (YYYY-MM), each year read from its own answer."""
    record = build_series()
    dataset = f"{PORTAL}:{cube.lower()}"
    years = sorted({period[:4] for period in values})
    return replace(
        record,
        source=replace(record.source, source_id=f"{cube}/[Measures].[Posisi Keuangan]/[Akun].[Akun].&[{key}]"),
        series=replace(
            record.series,
            id=f"{dataset}:posisi-keuangan:akun={key}",
            dataset=dataset,
            industry=industry,
            dimensions=(Dimension(name="Akun", key=key, label=label),),
        ),
        observations=tuple(
            Observation(period=period, value=value, file=answer_sha(period[:4]))
            for period, value in sorted(values.items())
        ),
        files=tuple(
            FileRef(sha256=answer_sha(year), role=FileRole.SOURCE_ANSWER, media_type="text/xml",
                    source_url=f"https://data.ojk.go.id/{cube}", edition=edition)
            for year in years
        ),
    )


def macro_series(periods: dict[str, float], frequency: Frequency = Frequency.QUARTERLY) -> SeriesRecord:
    """A macro series shaped like SEKI's GDP row 1: no industry, a unit, periods of one kind, the newest provisional."""
    record = series_record("TABEL7_1", "1", "PERTANIAN", {"2026-01": 0.0})
    newest = max(periods)
    return replace(
        record,
        source=replace(record.source, source_id=f"TABEL7_1/{frequency}/1"),
        series=replace(record.series, id=f"bi:seki:tabel7_1:{frequency}:row=1", dataset="bi:seki:tabel7_1",
                       industry=None, frequency=frequency, unit="Miliar Rp"),
        observations=tuple(
            Observation(period, value, answer_sha(period[:4]), provisional=period == newest)
            for period, value in sorted(periods.items())
        ),
        files=tuple(replace(record.files[0], sha256=answer_sha(year)) for year in sorted({p[:4] for p in periods})),
    )


def write_series_bundle(
    directory: Path, records: Sequence[SeriesRecord], run_id: str = "run-1", snapshot: Snapshot = Snapshot.FULL
) -> Path:
    with BundleWriter(
        directory, connector="ojk-stats", connector_version="0.1.0", run_id=run_id, snapshot=snapshot
    ) as bundle:
        for year in sorted({observation.period[:4] for record in records for observation in record.observations}):
            bundle.put_blob(answer_xml(year))
        for record in records:
            bundle.add(record)
    return directory


REPORT_PDF = b"%PDF-1.7 LPKSI 2025"


def report_record(text: str | None = None, report_id: str = "ojk:lpksi:2025") -> ReportRecord:
    """LPKSI 2025: when `text` is given, the record points at its blob and the PDF's (write_report_bundle)."""
    record = build_report()
    record = replace(record, report=replace(record.report, id=report_id, edition=report_id.rsplit(":", 1)[-1]),
                     source=replace(record.source, source_id=report_id))
    if text is None:
        return record
    pdf = hashlib.sha256(REPORT_PDF).hexdigest()
    return replace(
        record,
        text=replace(record.text, file=hashlib.sha256(text.encode()).hexdigest()),
        files=tuple(replace(file, sha256=pdf) for file in record.files),
    )


def write_report_bundle(directory: Path, texts: dict[str, str], run_id: str = "run-1") -> Path:
    """One report per ID, each with its text, all sharing one PDF's bytes."""
    with BundleWriter(directory, connector="reports", connector_version="0.1.0", run_id=run_id) as bundle:
        bundle.put_blob(REPORT_PDF)
        for report_id, text in texts.items():
            bundle.put_blob(text.encode())
            bundle.add(report_record(text, report_id))
    return directory

