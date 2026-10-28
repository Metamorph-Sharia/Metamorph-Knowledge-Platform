"""Valid records of each kind, for tests to start from and change one thing at a time."""

from __future__ import annotations

from dataclasses import replace

from metamorph_market import (
    BusinessType,
    Channel,
    Dimension,
    Entity,
    FileRef,
    FileRole,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    Observation,
    Series,
    SeriesRecord,
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


ANSWER_SHA = "c" * 64


def build_series(**changes: object) -> SeriesRecord:
    record = SeriesRecord(
        source=SourceRef(
            connector="ojk-stats",
            connector_version="0.1.0",
            source_id="BU_Syariah_PosisiKeuangan/[Measures].[Posisi Keuangan]/[Akun].&[110001010100]",
            url="https://data.ojk.go.id/SJKPublic/Dataset/Dataset/Dataset/346",
            fetched_at="2026-10-27T09:00:00+00:00",
        ),
        series=Series(
            id="ojk:portal:bu_syariah_posisikeuangan:posisi-keuangan:akun=110001010100",
            dataset="ojk:portal:bu_syariah_posisikeuangan",
            industry="Bank Umum Syariah",
            group="Informasi Keuangan Utama",
            metric="Laporan Posisi Keuangan",
            measure="Posisi Keuangan",
            dimensions=(Dimension(name="Akun", key="110001010100", label="003. 1. Kas dan Setara Kas"),),
        ),
        observations=(
            Observation(period="2026-07", value=15681990319.0, file=ANSWER_SHA),
            Observation(period="2026-08", value=13385111320.0, file=ANSWER_SHA),
        ),
        files=(
            FileRef(
                sha256=ANSWER_SHA,
                role=FileRole.SOURCE_ANSWER,
                media_type="text/xml",
                source_url="https://data.ojk.go.id/SJKPublic/datasource/",
                edition="2026-10-26",
            ),
        ),
        source_fields={"cube": "BU_Syariah_PosisiKeuangan", "catalog": "PORTALSJKCUBE_PERBANKAN"},
    )
    return replace(record, **changes)
