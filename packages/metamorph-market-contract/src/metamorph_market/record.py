"""The records a market connector emits (market contract 1.0): licensed entities, series, reports and releases.

Plain frozen dataclasses: they cross repository and process boundaries, so they hold values only.
The files they were read from (register editions, the source's answers, a report's PDF and its text) travel as
blobs referenced by sha256, never inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MARKET_CONTRACT_VERSION = "market-1.0"


class BusinessType(StrEnum):
    SHARIA = "sharia"
    CONVENTIONAL = "conventional"
    UNKNOWN = "unknown"  # the register doesn't say, or says something else


class Channel(StrEnum):
    """Where a licensed service reaches its users, as the register lists it."""

    ANDROID = "android"
    IOS = "ios"


class LicenseKind(StrEnum):
    """What the register's number grants. Until October 2021 OJK's list held both kinds."""

    LICENSE = "license"  # berizin: licensed by a decision, e.g. KEP-49/D.05/2017
    REGISTRATION = "registration"  # terdaftar: registered by a letter, e.g. S-735/NB.213/2019, not yet licensed
    UNKNOWN = "unknown"  # the number has neither form


class FileRole(StrEnum):
    REGISTER_EDITION = "register_edition"  # one published edition of the register, e.g. OJK's list for July 2026
    SOURCE_ANSWER = "source_answer"  # one answer of a statistics source, e.g. a portal table for one year
    SOURCE_TABLE = "source_table"  # one table of a statistics source as downloaded, e.g. a SEKI workbook
    SOURCE_REPORT = "source_report"  # a regulator's report as published, e.g. LPKSI 2025's PDF
    SOURCE_PAGE = "source_page"  # a part of a source's web page as published, e.g. a press release's body


class Frequency(StrEnum):
    """How often a series is observed, which its periods' form says: 2026-08, 2026-Q2, 2026-S1, 2025."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


@dataclass(frozen=True)
class SourceRef:
    connector: str
    connector_version: str
    source_id: str  # the source's own key: a license number as printed, a series' table, measure and members
    url: str | None  # the newest edition's page, when known
    fetched_at: str  # ISO datetime with time zone


@dataclass(frozen=True)
class License:
    number: str  # as printed, e.g. "KEP-49/D.05/2017"
    date: str | None  # ISO date
    kind: LicenseKind


@dataclass(frozen=True)
class Entity:
    id: str  # {register}:{license key}, e.g. "ojk:lpbbti:kep-49-d.05-2017"
    register: str  # {issuer}:{register}, e.g. "ojk:lpbbti"
    legal_name: str  # as in the newest listing
    names: tuple[str, ...]  # every other name listed: platform names, earlier legal names
    business_type: BusinessType
    license: License
    website: str | None  # as printed
    channels: tuple[Channel, ...]


@dataclass(frozen=True)
class Listing:
    """One edition's row for the license: where it is, and what it says."""

    edition: str  # ISO date
    file: str  # the edition's sha256
    page: int
    row: int  # the row's number as printed
    legal_name: str  # the company's name in this edition: a company keeps its record when it is renamed
    cells: dict[str, str]  # the row's cells under their printed headers


@dataclass(frozen=True)
class FileRef:
    sha256: str
    role: FileRole
    media_type: str
    source_url: str | None
    edition: str  # ISO date: the register edition's, or when the source last updated an answer's data


@dataclass(frozen=True)
class LicensedEntityRecord:
    source: SourceRef
    entity: Entity
    listings: tuple[Listing, ...]  # oldest edition first
    files: tuple[FileRef, ...]
    source_fields: dict[str, Any] = field(default_factory=dict)  # the newest listing's cells, unchanged
    contract_version: str = MARKET_CONTRACT_VERSION
    kind: str = "licensed_entity"


@dataclass(frozen=True)
class Dimension:
    """Which member of one of the table's dimensions a series is, e.g. the account Kas dan Setara Kas."""

    name: str  # e.g. "Akun"
    key: str  # stable across periods, e.g. "110001010100"
    label: str  # as shown, e.g. "003. 1. Kas dan Setara Kas"


@dataclass(frozen=True)
class Series:
    id: str  # {dataset}:{measure}:{dimension=key…}
    dataset: str  # {issuer}:{source}:{table}, e.g. "ojk:portal:bu_syariah_posisikeuangan"
    industry: str | None  # as the source names it, e.g. "Bank Umum Syariah"; None for a macro series
    group: str  # the source's group of information; "" when it has none
    metric: str  # the table's name, e.g. "Laporan Posisi Keuangan"
    measure: str  # what is counted, e.g. "Posisi Keuangan"
    dimensions: tuple[Dimension, ...]  # in the source's order
    frequency: Frequency = Frequency.MONTHLY
    unit: str | None = None  # as the source states it, e.g. "Miliar Rp"; never inferred


@dataclass(frozen=True)
class Observation:
    period: str  # YYYY-MM, YYYY-Qn, YYYY-Sn or YYYY, by the series' frequency
    value: float  # as the source gives it, never rescaled
    file: str  # the sha256 of the answer it was read from
    provisional: bool = False  # the source marks the period provisional, e.g. SEKI's "Aug*"


@dataclass(frozen=True)
class SeriesRecord:
    source: SourceRef
    series: Series
    observations: tuple[Observation, ...]  # oldest first
    files: tuple[FileRef, ...]
    source_fields: dict[str, Any] = field(default_factory=dict)  # what the source says of the series, unchanged
    contract_version: str = MARKET_CONTRACT_VERSION
    kind: str = "series"


class TextMethod(StrEnum):
    """How a report's text was read: from the PDF's text layer only, or with OCR on some pages."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"


@dataclass(frozen=True)
class Report:
    """A regulator's report, review, roadmap or masterplan. It has no legal force: never a rule."""

    id: str  # {issuer}:{family}:{edition} or {issuer}:{family}:{year}:{name}: ojk:lpksi:2025, ojk:roadmap:2023:rp3si
    issuer: str  # e.g. "ojk", "bi"
    family: str  # e.g. "lpksi", "keksi", "roadmap"
    edition: str  # as titled, e.g. "2025" or "2023-2027"
    title: str  # as published
    published_on: str | None  # ISO date, when known
    language: str  # e.g. "id"


@dataclass(frozen=True)
class Extraction:
    """How metamorph-pdf-text read the text, so it can be read again alike."""

    engine: str  # e.g. "mineru"
    engine_version: str
    tier: str  # e.g. "standard"
    ocr_mode: str  # e.g. "auto"
    pages_ocrd: int
    pages_fallen_back: int  # pages whose layout reading wasn't trusted, kept from the text layer


@dataclass(frozen=True)
class ReportText:
    """The report's text, page by page ("<!-- page N -->" markers), as a blob: the platform cuts its passages."""

    file: str  # the text's sha256
    pages: int
    method: TextMethod
    extraction: Extraction


@dataclass(frozen=True)
class ReportRecord:
    source: SourceRef
    report: Report
    text: ReportText
    files: tuple[FileRef, ...]  # the PDF as published
    source_fields: dict[str, Any] = field(default_factory=dict)  # what the source's page says of it, unchanged
    contract_version: str = MARKET_CONTRACT_VERSION
    kind: str = "report"


@dataclass(frozen=True)
class Release:
    """A regulator's press release: what it announced, in its own words, on its date. No legal force: never a rule."""

    id: str  # {issuer}:siaran-pers:{year}:{name}, the name being the page's: ojk:siaran-pers:2026:ojk-cabut-izin-…
    issuer: str  # e.g. "ojk"
    number: str | None  # as printed, e.g. "SP 188/DKPU/OJK/X/2026"; numbers repeat across years, and some have none
    title: str  # as listed
    published_on: str  # ISO date, as the source's listing dates it
    language: str  # e.g. "id"


@dataclass(frozen=True)
class ReleaseRecord:
    source: SourceRef
    release: Release
    text: str  # its words, paragraphs separated by blank lines: the platform cuts its passages
    files: tuple[FileRef, ...]  # the release's body as the page published it
    source_fields: dict[str, Any] = field(default_factory=dict)  # what the source says of it, unchanged
    contract_version: str = MARKET_CONTRACT_VERSION
    kind: str = "release"


MarketRecord = LicensedEntityRecord | SeriesRecord | ReportRecord | ReleaseRecord
