"""What the Knowledge and Retrieval layer may see: effective values, public content, live documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from metamorph_platform.domain.cross_references import cross_references
from metamorph_platform.domain.gate import Approval, HoldReason, MainText, hold_reasons
from metamorph_platform.domain.reading import passages, wording
from metamorph_platform.domain.structure.quality import affected_address, is_material
from metamorph_platform.domain.validity import SOURCE as LINKS

PUBLISHABLE_RIGHTS = frozenset({"public", "licensed"})
DATE_FIELDS = ("enacted_on", "promulgated_on", "effective_on")
UNKNOWN_STATUS = "unknown"
# Headings that only group others: their text is their children's, so it isn't published twice.
CONTAINER_KINDS = frozenset({"bab", "bagian", "paragraf", "memutuskan", "pengesahan"})
SECTION_ROOTS = frozenset({"penjelasan"})
TITLED_BY_CHILDREN = frozenset({"bab", "lampiran"})  # an annex and its chapters carry their own text when childless
REFERS_TO = "refers_to"  # a provision naming another of the same document: "sebagaimana dimaksud dalam Pasal 5"
WITHIN_DOCUMENT = "high"  # such a link's confidence: its target is a provision the text has

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
    heading_path: tuple[str, ...] = ()  # each provision from the root down to this one, named: "BAB II …", "Pasal 5"
    depth: int = 0  # how many provisions hold it
    wording: str = ""  # the body to read or embed: no heading lines of its own, no page furniture


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
class ReviewNote:
    """A structure warning published with the document, for review: on the provision it names, or on the document
    when it names none. The document is published all the same (domain/gate.py)."""

    address: str | None
    note: str


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
    reviews: tuple[ReviewNote, ...] = ()


def must_be_removed(snapshot: DocumentSnapshot) -> bool:
    """Suppressed by a curator, or no source holds it any more.

    A document a source stopped listing is still published: a regulation doesn't stop existing because
    a website dropped it. Only a document no source record points to (e.g. its ID was corrected) goes.
    """
    return snapshot.suppressed or not snapshot.sources


def hold_reasons_of(snapshot: DocumentSnapshot, parser_version: str) -> tuple[HoldReason, ...]:
    """Why the publish gate holds the document back; empty when it may be published."""
    return hold_reasons(
        snapshot.id,
        _effective_main_texts(snapshot),
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
    provisions = _provisions(snapshot.provisions, {text.sha256 for text in published_texts}, texts or {})
    return PublishedDocument(
        id=snapshot.id,
        values=values,
        aliases=snapshot.aliases,
        sources=snapshot.sources,
        files=_publishable(snapshot.files),
        texts=published_texts,
        curated=curated,
        provisions=provisions,
        links=snapshot.links + _references_within(snapshot.id, provisions, texts or {}),
        status_events=snapshot.status_events,
        reviews=_review_notes(snapshot),
    )


def _effective_main_texts(snapshot: DocumentSnapshot) -> tuple[MainText, ...]:
    """The main texts as the parser read them: a curator's correction in place of the source's wording."""
    corrected = {correction.corrects_sha256: correction.sha256 for correction in snapshot.corrections}
    return tuple(replace(text, sha256=corrected.get(text.sha256, text.sha256)) for text in snapshot.main_texts)


def _review_notes(snapshot: DocumentSnapshot) -> tuple[ReviewNote, ...]:
    """The warnings left to review: a curator who approved a text's problems as they are has reviewed them."""
    approved = set(snapshot.approvals)
    return tuple(
        ReviewNote(affected_address(problem), problem)
        for text in _effective_main_texts(snapshot)
        if Approval(text.sha256, text.problems) not in approved
        for problem in text.problems
        if not is_material(problem)
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
    by_address = {record.address: record for record in records}
    published = []
    for record in records:
        if record.text_sha256 not in published_texts or record.text_sha256 not in texts:
            continue
        body = "" if _groups_only(record, parents) else texts[record.text_sha256][record.char_start : record.char_end]
        path = heading_path(record, by_address)
        published.append(PublishedProvision(record, body, path, len(path) - 1, wording(body, record) if body else ""))
    return tuple(published)


def _groups_only(record: ProvisionRecord, parents: set[str | None]) -> bool:
    """A heading whose text is its children's, so it isn't published twice. An annex, or an annex's chapter, with
    nothing nested in it carries its own."""
    if record.address in SECTION_ROOTS:
        return True
    if record.kind in TITLED_BY_CHILDREN:
        return record.address in parents
    return record.kind in CONTAINER_KINDS


def heading_path(record: ProvisionRecord, by_address: Mapping[str, ProvisionRecord]) -> tuple[str, ...]:
    """The provisions from the root down to `record`, each named by its label and heading: what to read a provision
    under ("BAB II KEGIATAN USAHA", "Bagian Kesatu Jenis Kegiatan", "Pasal 5", "(1)")."""
    names: list[str] = []
    seen: set[str] = set()
    node: ProvisionRecord | None = record
    while node is not None and node.address not in seen:
        seen.add(node.address)
        names.append(" ".join(part for part in (node.label, node.heading) if part))
        node = by_address.get(node.parent_address) if node.parent_address else None
    return tuple(reversed(names))


def _references_within(
    document_id: str, provisions: tuple[PublishedProvision, ...], texts: Mapping[str, str]
) -> tuple[LinkRecord, ...]:
    """Each provision's references to the document's other provisions, found in its own wording: a reference in an
    article's paragraph is the paragraph's, as domain/reading.py reads each character in its innermost provision."""
    by_text: dict[str, list[ProvisionRecord]] = {}
    for provision in provisions:
        by_text.setdefault(provision.record.text_sha256, []).append(provision.record)
    found: dict[tuple[str, str], LinkRecord] = {}
    for sha256, records in by_text.items():
        addresses = {record.address for record in records}
        for passage in passages(texts[sha256], records):
            for reference in cross_references(passage.text, within=passage.address, addresses=addresses):
                if passage.address not in (None, reference.address):
                    link = LinkRecord(REFERS_TO, passage.address, document_id, reference.address, None, WITHIN_DOCUMENT)
                    found[(passage.address, reference.address)] = link
    return tuple(found.values())


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
