"""What the Knowledge and Retrieval layer may see: effective values, public content, live documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from metamorph_platform.domain.gate import Approval, HoldReason, MainText, hold_reasons
from metamorph_platform.domain.validity import SOURCE as LINKS

PUBLISHABLE_RIGHTS = frozenset({"public", "licensed"})
DATE_FIELDS = ("enacted_on", "promulgated_on", "effective_on")
UNKNOWN_STATUS = "unknown"
# Headings that only group others: their text is their children's, so it isn't published twice.
CONTAINER_KINDS = frozenset({"bab", "bagian", "paragraf", "memutuskan", "pengesahan"})
SECTION_ROOTS = frozenset({"penjelasan"})

# The document fields a curator may override; anything else is refused before it reaches publishing.
OVERRIDABLE_FIELDS = frozenset(
    {
        "citation",
        "title",
        "kind",
        "status",
        "status_as_of",
        "enacted_on",
        "promulgated_on",
        "effective_on",
        "year",
    }
)


@dataclass(frozen=True)
class Override:
    field: str
    value: Any


@dataclass(frozen=True)
class SourceRecord:
    connector: str
    source_id: str
    url: str
    fetched_at: str
    missing_since: str | None = None


@dataclass(frozen=True)
class StoredContent:
    """A file or text of the document, with where its bytes live."""

    sha256: str
    rights: str
    storage_key: str
    details: Mapping[str, Any] = field(default_factory=dict)  # role, media_type, language, origin, …


@dataclass(frozen=True)
class ProvisionRecord:
    """A provision of one of the document's texts, located by character offsets into that text."""

    text_sha256: str
    address: str
    kind: str
    label: str
    ordinal: int
    char_start: int
    char_end: int
    parent_address: str | None = None
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None


@dataclass(frozen=True)
class PublishedProvision:
    record: ProvisionRecord
    body: str  # the provision's text; empty for headings that only group others


@dataclass(frozen=True)
class LinkRecord:
    """A resolved link from this document to another (which may not be published itself)."""

    type: str
    from_address: str | None
    to_document: str
    to_address: str | None
    effective_on: date | None
    confidence: str


@dataclass(frozen=True)
class StatusEventRecord:
    address: str | None  # None: the whole document
    status: str
    effective_from: date | None
    source: str  # a connector, or "links" when derived from another document's amending or revoking link


@dataclass(frozen=True)
class TextCorrection:
    """A curator's corrected wording of one of the document's texts (an overlay: the source text stays)."""

    corrects_sha256: str
    sha256: str
    storage_key: str


@dataclass(frozen=True)
class DocumentSnapshot:
    """Everything the registry and curation know about one document, read at one moment."""

    id: str
    values: Mapping[str, Any]  # the registry's document columns
    aliases: tuple[str, ...]
    sources: tuple[SourceRecord, ...]
    files: tuple[StoredContent, ...]
    texts: tuple[StoredContent, ...]
    overrides: tuple[Override, ...] = ()
    suppressed: bool = False
    provisions: tuple[ProvisionRecord, ...] = ()
    links: tuple[LinkRecord, ...] = ()
    status_events: tuple[StatusEventRecord, ...] = ()
    stated_dates: Mapping[str, date | None] = field(default_factory=dict)  # what the document's own text says
    main_texts: tuple[MainText, ...] = ()  # what the publish gate reads (domain/gate.py), as the sources sent them
    approvals: tuple[Approval, ...] = ()
    corrections: tuple[TextCorrection, ...] = ()  # the active ones, of the document's current texts


@dataclass(frozen=True)
class PublishedDocument:
    id: str
    values: Mapping[str, Any]
    aliases: tuple[str, ...]
    sources: tuple[SourceRecord, ...]
    files: tuple[StoredContent, ...]
    texts: tuple[StoredContent, ...]
    curated: bool
    provisions: tuple[PublishedProvision, ...] = ()
    links: tuple[LinkRecord, ...] = ()
    status_events: tuple[StatusEventRecord, ...] = ()


def must_be_removed(snapshot: DocumentSnapshot) -> bool:
    """Suppressed by a curator, or no source holds it any more.

    A document a source stopped listing is still published: a regulation doesn't stop existing because
    a website dropped it. Only a document no source record points to (e.g. its ID was corrected) goes.
    """
    return snapshot.suppressed or not snapshot.sources


def hold_reasons_of(snapshot: DocumentSnapshot, parser_version: str) -> tuple[HoldReason, ...]:
    """Why the publish gate holds the document back; empty when it may be published."""
    corrected = {correction.corrects_sha256: correction.sha256 for correction in snapshot.corrections}
    return hold_reasons(
        snapshot.id,
        tuple(replace(text, sha256=corrected.get(text.sha256, text.sha256)) for text in snapshot.main_texts),
        snapshot.approvals,
        acquired_roles=(file.details.get("role", "file") for file in snapshot.files),
        parser_version=parser_version,
    )


def publication_of(snapshot: DocumentSnapshot, texts: Mapping[str, str] | None = None) -> PublishedDocument:
    """What `published` holds for a document that may be published (see must_be_removed, hold_reasons_of).

    `texts`: the decoded texts the provisions point into, by sha256.
    """
    values, curated = effective_values(_derived_values(snapshot), snapshot.overrides)
    published_texts = _publishable(effective_texts(snapshot.texts, snapshot.corrections))
    return PublishedDocument(
        id=snapshot.id,
        values=values,
        aliases=snapshot.aliases,
        sources=snapshot.sources,
        files=_publishable(snapshot.files),
        texts=published_texts,
        curated=curated,
        provisions=_provisions(snapshot.provisions, {text.sha256 for text in published_texts}, texts or {}),
        links=snapshot.links,
        status_events=snapshot.status_events,
    )


def _derived_values(snapshot: DocumentSnapshot) -> dict[str, Any]:
    """What the sources didn't say, from what the platform derived: dates the text states, status from links."""
    values = dict(snapshot.values)
    for name in DATE_FIELDS:
        if values.get(name) is None and snapshot.stated_dates.get(name) is not None:
            values[name] = snapshot.stated_dates[name]
    if values.get("status") == UNKNOWN_STATUS:
        values["status"] = latest_document_status(snapshot.status_events) or UNKNOWN_STATUS
    return values


def latest_document_status(events: tuple[StatusEventRecord, ...]) -> str | None:
    """The latest whole-document status other documents' links give (undated ones count as earliest)."""
    derived = [event for event in events if event.address is None and event.source == LINKS]
    if not derived:
        return None
    return max(derived, key=lambda event: event.effective_from or date.min).status


def _provisions(
    records: tuple[ProvisionRecord, ...], published_texts: set[str], texts: Mapping[str, str]
) -> tuple[PublishedProvision, ...]:
    parents = {record.parent_address for record in records}
    return tuple(
        PublishedProvision(
            record,
            "" if _groups_only(record, parents) else texts[record.text_sha256][record.char_start : record.char_end],
        )
        for record in records
        if record.text_sha256 in published_texts and record.text_sha256 in texts
    )


def _groups_only(record: ProvisionRecord, parents: set[str | None]) -> bool:
    if record.kind in CONTAINER_KINDS or record.address in SECTION_ROOTS:
        return True
    return record.kind == "lampiran" and record.address in parents  # an annex with chapters: they carry its text


def effective_values(values: Mapping[str, Any], overrides: tuple[Override, ...]) -> tuple[dict[str, Any], bool]:
    """Source values with each active override applied; True when any override changed something."""
    effective = dict(values)
    for override in overrides:
        if override.field not in OVERRIDABLE_FIELDS:
            raise ValueError(f"{override.field!r} can't be overridden; allowed: {sorted(OVERRIDABLE_FIELDS)}")
        effective[override.field] = override.value
    return effective, effective != dict(values)


def effective_texts(
    texts: tuple[StoredContent, ...], corrections: tuple[TextCorrection, ...]
) -> tuple[StoredContent, ...]:
    """Each text with its curator's correction applied: the corrected wording, and nothing else changed.

    Its rights, language, origin and method stay the source's: nothing marks it as corrected (a decision of
    the Metamorph team); the correction itself, and both wordings, stay in curation for anyone who asks.
    """
    corrected = {correction.corrects_sha256: correction for correction in corrections}
    return tuple(
        replace(text, sha256=corrected[text.sha256].sha256, storage_key=corrected[text.sha256].storage_key)
        if text.sha256 in corrected
        else text
        for text in texts
    )


def _publishable(contents: tuple[StoredContent, ...]) -> tuple[StoredContent, ...]:
    return tuple(content for content in contents if content.rights in PUBLISHABLE_RIGHTS)
