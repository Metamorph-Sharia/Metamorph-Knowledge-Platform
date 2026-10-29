"""Valid records of each kind, for tests to start from and change one thing at a time."""

from __future__ import annotations

from dataclasses import replace

from metamorph_market import (
    BusinessType,
    Channel,
    Dimension,
    Entity,
    Extraction,
    FileRef,
    FileRole,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    Observation,
    Release,
    ReleaseRecord,
    Report,
    ReportRecord,
    ReportText,
    Series,
    SeriesRecord,
    SourceRef,
    TextMethod,
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


REPORT_PDF_SHA = "d" * 64
REPORT_TEXT_SHA = "e" * 64


def build_report(**changes: object) -> ReportRecord:
    record = ReportRecord(
        source=SourceRef(
            connector="reports",
            connector_version="0.1.0",
            source_id="Laporan-Perkembangan-Keuangan-Syariah-Indonesia-2025",
            url="https://ojk.go.id/id/kanal/syariah/data-dan-statistik/laporan-perkembangan-keuangan-syariah-indonesia/"
            "Pages/Laporan-Perkembangan-Keuangan-Syariah-Indonesia-2025.aspx",
            fetched_at="2026-10-28T09:00:00+00:00",
        ),
        report=Report(
            id="ojk:lpksi:2025",
            issuer="ojk",
            family="lpksi",
            edition="2025",
            title="Laporan Perkembangan Keuangan Syariah Indonesia 2025",
            published_on=None,
            language="id",
        ),
        text=ReportText(
            file=REPORT_TEXT_SHA,
            pages=244,
            method=TextMethod.OCR,
            extraction=Extraction(
                engine="mineru",
                engine_version="4.0.12",
                tier="standard",
                ocr_mode="auto",
                pages_ocrd=22,
                pages_fallen_back=3,
            ),
        ),
        files=(
            FileRef(
                sha256=REPORT_PDF_SHA,
                role=FileRole.SOURCE_REPORT,
                media_type="application/pdf",
                source_url="https://ojk.go.id/id/kanal/syariah/data-dan-statistik/laporan-perkembangan-keuangan-syariah-"
                "indonesia/Documents/Laporan%20Perkembangan%20Keuangan%20Syariah%20Indonesia%20%28LPKSI%29%202025.pdf",
                edition="2026-10-28",
            ),
        ),
        source_fields={"page_title": "Laporan Perkembangan Keuangan Syariah Indonesia 2025"},
    )
    return replace(record, **changes)



RELEASE_PAGE_SHA = "f" * 64
RELEASE_PAGE = "https://ojk.go.id/id/berita-dan-kegiatan/siaran-pers/Pages/OJK-Cabut-Izin-Usaha-PT-Porto-Ventura-Kapital.aspx"


def build_release(**changes: object) -> ReleaseRecord:
    record = ReleaseRecord(
        source=SourceRef(
            connector="reports",
            connector_version="0.2.0",
            source_id="OJK-Cabut-Izin-Usaha-PT-Porto-Ventura-Kapital",
            url=RELEASE_PAGE,
            fetched_at="2026-10-28T09:00:00+00:00",
        ),
        release=Release(
            id="ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital",
            issuer="ojk",
            number="SP 188/DKPU/OJK/X/2026",
            title="Siaran Pers: OJK Cabut Izin Usaha PT Porto Ventura Kapital",
            published_on="2026-10-08",
            language="id",
        ),
        text="SP 188/DKPU/OJK/X/2026\n\nSIARAN PERS\n\nOJK CABUT IZIN USAHA PT PORTO VENTURA KAPITAL\n\n"
        "Jakarta, 8 Oktober 2026. Otoritas Jasa Keuangan (OJK) mencabut izin usaha PT Porto Ventura Kapital.",
        files=(
            FileRef(
                sha256=RELEASE_PAGE_SHA,
                role=FileRole.SOURCE_PAGE,
                media_type="text/html; charset=utf-8",
                source_url=RELEASE_PAGE,
                edition="2026-10-08",
            ),
        ),
        source_fields={"pdf": "https://ojk.go.id/id/berita-dan-kegiatan/siaran-pers/Documents/Pages/"
                       "OJK-Cabut-Izin-Usaha-PT-Porto-Ventura-Kapital/SP%20188.pdf"},
    )
    return replace(record, **changes)
