"""Market records and bundles for the platform's tests: licenses listed in given editions, each edition its PDF."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from market_samples import build_record
from metamorph_market import (
    BundleWriter,
    BusinessType,
    FileRef,
    FileRole,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
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
