"""The records a market connector emits (market contract 1.0).

Plain frozen dataclasses: they cross repository and process boundaries, so they hold values only.
The register editions travel as blobs referenced by sha256, never inline.
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


@dataclass(frozen=True)
class SourceRef:
    connector: str
    connector_version: str
    source_id: str  # the license number, as printed
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
    edition: str  # ISO date


@dataclass(frozen=True)
class LicensedEntityRecord:
    source: SourceRef
    entity: Entity
    listings: tuple[Listing, ...]  # oldest edition first
    files: tuple[FileRef, ...]
    source_fields: dict[str, Any] = field(default_factory=dict)  # the newest listing's cells, unchanged
    contract_version: str = MARKET_CONTRACT_VERSION
    kind: str = "licensed_entity"
