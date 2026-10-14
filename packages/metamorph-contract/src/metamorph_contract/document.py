"""The normalized document every connector emits (contract v2).

Plain frozen dataclasses: they cross repository and process boundaries, so they hold
values only. Texts and files travel as blobs referenced by sha256, never inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "2.0"


class Kind(StrEnum):
    """What kind of instrument this is, which decides how much legal weight an answer gives it."""

    LAW = "law"  # UU, Perppu
    REGULATION = "regulation"  # PP, Perpres, POJK, PBI, ministerial rules
    IMPLEMENTING_RULE = "implementing_rule"  # SEOJK, PADK, PADG, SEBI
    FATWA = "fatwa"
    GUIDELINE = "guideline"  # DSN-MUI pedoman
    CIRCULAR = "circular"  # DSN-MUI ta'limat
    EXPLANATORY = "explanatory"  # official FAQ, abstract, summary


class Status(StrEnum):
    IN_FORCE = "in_force"
    AMENDED = "amended"  # in force, some provisions changed by a later instrument
    PARTLY_REVOKED = "partly_revoked"
    REVOKED = "revoked"
    NOT_YET_IN_FORCE = "not_yet_in_force"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CONFLICT = "conflict"
    NONE = "none"


class FileRole(StrEnum):
    MAIN = "main"
    ANNEX = "annex"
    ABSTRACT = "abstract"
    FAQ = "faq"
    GUIDE = "guide"  # technical guidance (e.g. BI juknis)
    PAGE_HTML = "page_html"  # the source's detail page
    API_PAYLOAD = "api_payload"  # a raw API response the texts came from
    OTHER = "other"


class TextOrigin(StrEnum):
    SELF_EXTRACTED = "self_extracted"  # we extracted it from an official file
    SOURCE_TEXT = "source_text"  # a source supplied the original-language text
    SOURCE_TRANSLATION = "source_translation"  # a source supplied a translation


class ExtractionMethod(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    SOURCE = "source"  # supplied ready-made by the source


class Rights(StrEnum):
    PUBLIC = "public"
    LICENSED = "licensed"
    RESTRICTED = "restricted"  # never bundled


class Relation(StrEnum):
    AMENDS = "amends"
    REVOKES = "revokes"
    PARTLY_REVOKES = "partly_revokes"
    SUPERSEDES = "supersedes"
    IMPLEMENTS = "implements"  # PADK/SEOJK → a POJK article; pedoman → a fatwa
    LEGAL_BASIS = "legal_basis"  # "Mengingat"
    ADOPTS_FATWA = "adopts_fatwa"  # a POJK/PBI → a DSN-MUI fatwa
    CHANGES_FATWA = "changes_fatwa"  # a ta'limat → a fatwa
    REFERS_TO = "refers_to"


class FoundIn(StrEnum):
    TEXT = "text"
    SOURCE_METADATA = "source_metadata"


@dataclass(frozen=True)
class SourceRef:
    """Where this record came from: one source's view of one document."""

    connector: str  # e.g. "ojk", "bpk", "bi-website", "dsn-fatwa"
    connector_version: str
    source_id: str  # stable at the source (team interface rule 1)
    url: str
    fetched_at: str  # ISO 8601 datetime with timezone


@dataclass(frozen=True)
class Dates:
    enacted: str | None = None  # ISO 8601 dates
    promulgated: str | None = None
    effective: str | None = None


@dataclass(frozen=True)
class StatusClaim:
    value: Status
    source: str  # who says so, e.g. "jdih_ojk", "bpk", "regalert"
    as_of: str | None = None  # ISO date the source last confirmed it


@dataclass(frozen=True)
class DocumentInfo:
    id: str  # canonical, see identity.py
    id_confidence: Confidence
    id_evidence: str
    issuer: str
    family: str
    number: str
    year: int | None
    citation: str  # how people cite it, e.g. "POJK 5/POJK.05/2014"
    title: str
    language: str  # ISO 639-1 of the authoritative text, e.g. "id"
    kind: Kind
    status: StatusClaim
    dates: Dates = field(default_factory=Dates)
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileRef:
    sha256: str
    role: FileRole
    media_type: str
    source_url: str | None
    rights: Rights
    title: str | None = None
    pages: int | None = None


@dataclass(frozen=True)
class TextRef:
    """A UTF-8 text blob. When `paged`, pages are separated by page markers (paged_text.py)."""

    sha256: str
    language: str
    origin: TextOrigin
    method: ExtractionMethod
    rights: Rights
    paged: bool
    of_file: str | None = None  # sha256 of the file it was extracted from, if any


@dataclass(frozen=True)
class Provision:
    """One addressable unit of a text, e.g. "pasal-115/ayat-1", located by character offsets."""

    address: str
    kind: str  # bab | bagian | paragraf | pasal | ayat | huruf | angka | penjelasan | lampiran | section …
    label: str
    text: str  # sha256 of the TextRef it indexes into
    char_start: int
    char_end: int
    parent: str | None = None
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class Citation:
    """A reference this document makes to another, as found. The platform resolves it into a link."""

    relation: Relation
    target_text: str
    evidence: str
    found_in: FoundIn
    confidence: Confidence
    target_id: str | None = None  # canonical ID, when the connector can tell
    from_address: str | None = None
    to_address: str | None = None


@dataclass(frozen=True)
class NormalizedDocument:
    source: SourceRef
    document: DocumentInfo
    files: tuple[FileRef, ...]
    texts: tuple[TextRef, ...] = ()
    provisions: tuple[Provision, ...] = ()
    citations: tuple[Citation, ...] = ()
    source_fields: dict[str, Any] = field(default_factory=dict)  # the source's own fields, unchanged
    contract_version: str = CONTRACT_VERSION
