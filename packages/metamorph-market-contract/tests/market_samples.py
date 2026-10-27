"""A valid licensed-entity record, for tests to start from and change one thing at a time."""

from __future__ import annotations

from dataclasses import replace

from metamorph_market import (
    BusinessType,
    Channel,
    Entity,
    FileRef,
    FileRole,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    SourceRef,
)

EDITION_SHA = "a" * 64
JULY = "2026-07-31"


def build_record(**changes: object) -> LicensedEntityRecord:
    record = LicensedEntityRecord(
        source=SourceRef(
            connector="ojk-register",
            connector_version="0.1.0",
            source_id="KEP-123/D.05/2019",
            url=None,
            fetched_at="2026-10-27T09:00:00+00:00",
        ),
        entity=Entity(
            id="ojk:lpbbti:kep-123-d.05-2019",
            register="ojk:lpbbti",
            legal_name="PT Ammana Fintek Syariah",
            names=("Ammana",),
            business_type=BusinessType.SHARIA,
            license=License(number="KEP-123/D.05/2019", date="2019-12-13", kind=LicenseKind.LICENSE),
            website="https://ammana.id/",
            channels=(Channel.ANDROID, Channel.IOS),
        ),
        listings=(
            Listing(
                edition=JULY,
                file=EDITION_SHA,
                page=1,
                row=12,
                legal_name="PT Ammana Fintek Syariah",
                cells={"Nama Perusahaan": "PT Ammana Fintek Syariah", "Jenis Usaha": "Syariah"},
            ),
        ),
        files=(
            FileRef(
                sha256=EDITION_SHA,
                role=FileRole.REGISTER_EDITION,
                media_type="application/pdf",
                source_url=None,
                edition=JULY,
            ),
        ),
        source_fields={"Nama Perusahaan": "PT Ammana Fintek Syariah", "Jenis Usaha": "Syariah"},
    )
    return replace(record, **changes)
