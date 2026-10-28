"""The records a market connector emits (market contract 1.0): licensed entities and series.

Plain frozen dataclasses: they cross repository and process boundaries, so they hold values only.
The files they were read from (register editions, the source's answers) travel as blobs referenced by sha256,
never inline.
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


MarketRecord = LicensedEntityRecord | SeriesRecord
