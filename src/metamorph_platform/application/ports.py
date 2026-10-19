"""What the use cases need from the outside world, and nothing more (one port per role).

Each port has a PostgreSQL or S3 implementation in `adapters/` and an in-memory fake in `tests/fakes.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from metamorph_contract import Manifest, NormalizedDocument

from metamorph_platform.domain.citations import TextCitation
from metamorph_platform.domain.curation import ActiveOverride
from metamorph_platform.domain.dates import TextDates
from metamorph_platform.domain.health import Health, HealthFacts
from metamorph_platform.domain.loading import ReviewKind, SaveOutcome
from metamorph_platform.domain.publishing import DocumentSnapshot, PublishedDocument
from metamorph_platform.domain.reviews import TextStanding
from metamorph_platform.domain.structure import Structure
from metamorph_platform.domain.validity import DatedLink, ProvisionExpiry, StatusChange


class BundleAlreadyLoaded(Exception):
    """This connector run was loaded before; loading it again would double-count nothing, so it is refused."""


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    storage_key: str
    media_type: str
    size_bytes: int


class BlobStore(Protocol):
    def store(self, sha256: str, source: Path, media_type: str) -> StoredBlob:
        """Write-once and content-addressed: storing bytes that are already there is a no-op."""


class BlobReader(Protocol):
    def read(self, storage_key: str) -> bytes: ...


class IngestLedger(Protocol):
    def start_bundle(self, manifest: Manifest, uri: str) -> int:
        """Record a bundle as received; raises BundleAlreadyLoaded for a connector run seen before."""

    def quarantine(self, bundle_id: int, line: int, raw: str, problems: list[str], source_id: str | None) -> None: ...

    def finish_bundle(self, bundle_id: int, counts: Mapping[str, int]) -> None: ...

    def fail_bundle(self, bundle_id: int, error: str) -> None: ...


class Registry(Protocol):
    """The loader's view of the system of record."""

    def assigned_id(self, connector: str, source_id: str) -> str | None:
        """The ID a curator gave this source record, if any (curation.id_assignment)."""

    def package_hash(self, connector: str, source_id: str) -> str | None: ...

    def seen_again(self, connector: str, source_id: str, bundle_id: int) -> None: ...

    def save(
        self,
        document: NormalizedDocument,
        *,
        bundle_id: int,
        package_hash: str,
        blobs: Mapping[str, StoredBlob],
    ) -> SaveOutcome:
        """Store one source record and the document it describes, atomically."""

    def mark_missing(self, connector: str, present: set[str]) -> int:
        """Records of `connector` absent from a full snapshot; returns how many newly went missing."""


class Overrides(Protocol):
    """The loader's view of curation: corrections in force, and the conflicts a source change raises."""

    def active(self, document_id: str) -> list[ActiveOverride]: ...

    def raise_conflict(self, override_id: int, source_value: Any) -> None:
        """Open a conflict for the override, or update the open one with the source's latest value."""


class ReviewQueue(Protocol):
    def ensure_open(self, kind: ReviewKind, subject: Mapping[str, Any]) -> None:
        """Open a review item unless one is already open for the same subject."""


@dataclass(frozen=True)
class OpenReview:
    id: int
    kind: ReviewKind
    subject: Mapping[str, Any]


class OpenReviews(Protocol):
    """The queue's open items, what the registry now holds about each, and settling one that needs no person."""

    def open_items(self) -> list[OpenReview]: ...

    def text_standing(self, document_id: str, text_sha256: str) -> TextStanding | None:
        """None when the registry no longer has that text version."""

    def still_unlinked(self, document_id: str, target_text: str) -> bool:
        """Whether the document still has a citation with that text and no link."""

    def document_exists(self, document_id: str) -> bool: ...

    def settle(self, item_id: int, reason: str) -> None:
        """Resolve the item as the platform, with the reason, audited like a curator's decision."""


class PublicationSource(Protocol):
    def documents_to_publish(self, everything: bool = False) -> list[str]:
        """Documents changed since they were last published (or all of them), plus published ones now gone."""

    def snapshot(self, document_id: str) -> DocumentSnapshot | None: ...


class PublishedStore(Protocol):
    def replace(self, document: PublishedDocument) -> bool:
        """Write the document's published rows; True when it was not published before."""

    def remove(self, document_id: str) -> bool:
        """True when there was something to remove."""


@dataclass(frozen=True)
class TextToParse:
    """A current main text of a document, in the language the parser reads (Indonesian)."""

    text_version_id: int
    document_id: str
    issuer: str
    family: str
    sha256: str
    storage_key: str


@dataclass(frozen=True)
class ParsedText:
    text: TextToParse
    parser_version: str
    structure: Structure
    citations: list[TextCitation]
    dates: TextDates


class ParsedTexts(Protocol):
    def texts_to_parse(self, parser_version: str, everything: bool = False) -> list[TextToParse]:
        """Current main texts not yet parsed by this parser version (or all of them)."""

    def save(self, parsed: ParsedText) -> None:
        """Replace the text's parsed provisions and citations and its stated dates, atomically."""


@dataclass(frozen=True)
class OpenCitation:
    """A citation not linked yet: its target isn't held, or it hasn't been tried."""

    id: int
    document_id: str
    relation: str
    target_text: str
    target_id: str | None
    from_address: str | None
    to_address: str | None
    confidence: str


@dataclass(frozen=True)
class NewLink:
    type: str
    from_document: str
    from_address: str | None
    to_document: str
    to_address: str | None
    method: str
    confidence: str


class CitationLinks(Protocol):
    def open_citations(self) -> list[OpenCitation]: ...

    def document_ids(self) -> set[str]: ...

    def unambiguous_aliases(self) -> dict[str, str]:
        """Alias key → the one document it names; a key naming several documents is left out."""

    def link(self, citation_id: int, link: NewLink) -> None:
        """Find or create the link and point the citation at it."""

    def drop_unsupported_links(self) -> int:
        """Remove links no citation supports any more (their citations were replaced); curated ones stay."""


class Validity(Protocol):
    def dated_links(self) -> list[DatedLink]:
        """Every link, dated by when its document takes effect (a source's date, else the date its text states)."""

    def apply(self, changes: list[StatusChange], expiries: list[ProvisionExpiry]) -> int:
        """Make the link-derived status events and provision end dates exactly these; returns documents changed."""


class HealthLog(Protocol):
    def facts(self) -> HealthFacts:
        """Each connector's last good and last failed load, open review items, and the time now."""

    def record(self, health: Health) -> None: ...


class CurationRefused(Exception):
    """The action can't apply as asked (no such document, the ID is taken, the item was decided); says why."""


@dataclass(frozen=True)
class Curator:
    username: str
    display_name: str


class CurationActions(Protocol):
    """The Metamorph team's changes. Each is atomic, writes curation.audit_log with the state before it,
    and marks the documents it touches for the next publish."""

    def correct(self, curator: Curator, document_id: str, field: str, value: Any, reason: str) -> None: ...

    def withdraw_correction(self, curator: Curator, document_id: str, field: str, reason: str) -> None: ...

    def suppress(self, curator: Curator, document_id: str, reason: str) -> None: ...

    def restore(self, curator: Curator, document_id: str, reason: str) -> None: ...

    def decide_review(self, curator: Curator, item_id: int, state: str, note: str) -> None: ...

    def assign_id(self, curator: Curator, document_id: str, new_id: str, reason: str) -> None:
        """Rename the document, and keep its source records loading under the new ID."""

    def link_citation(self, curator: Curator, citation_id: int, target_id: str, reason: str) -> None: ...

    def resolve_conflict(self, curator: Curator, conflict_id: int, state: str, note: str) -> None:
        """`accepted_source` withdraws the correction; `kept_override` keeps it."""

    def record(self, curator: Curator, action: str, target: Mapping[str, Any], after: Any, reason: str) -> None:
        """Audit an action another use case carried out (e.g. a manual document's load)."""
