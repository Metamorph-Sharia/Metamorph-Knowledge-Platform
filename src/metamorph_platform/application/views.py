"""What the curation pages show: read models, and the query port that fills them.

Queries, not use cases: no rule decides anything here. Each model is plain, immutable data, so the web
adapter renders it without knowing where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from metamorph_platform.domain.gate import Check, HoldReason

REVIEW_KINDS = ("conflict", "unresolved_citation", "quarantine")  # structure and identity: the held list
PAGE_SIZE = 50
SEARCH_PAGE_SIZE = 20
SEARCH_KINDS = ("documents", "articles")  # what a search lists: matching documents, or matching articles
# Whether the assistant sees a document: published; held back by the publish gate; suppressed; or never published.
STATES = ("published", "held", "suppressed", "unpublished")
FACETS = ("issuer", "family", "year", "status", "state")


@dataclass(frozen=True)
class CheckRow:
    name: str
    severity: str
    detail: str


@dataclass(frozen=True)
class BundleRow:
    connector: str
    run_id: str
    state: str
    received_at: datetime
    loaded: int  # documents new or changed
    unchanged: int
    quarantined: int


@dataclass(frozen=True)
class Dashboard:
    health_status: str | None  # None before the first health check
    health_taken_at: datetime | None
    checks: tuple[CheckRow, ...]
    documents_by_issuer: tuple[tuple[str, int], ...]
    published: int
    open_reviews: tuple[tuple[str, int], ...]  # every review kind, zero included
    recent_bundles: tuple[BundleRow, ...]
    held: int = 0  # documents the publish gate holds back
    held_published: int = 0  # of those, the ones whose last good version is still published


@dataclass(frozen=True)
class ReviewRow:
    id: int
    kind: str
    created_at: datetime
    document_id: str | None
    document_title: str | None
    summary: str  # what to look at, in a line: the problems, the citation, the bundle line
    subject: dict[str, Any]


@dataclass(frozen=True)
class ReviewPage:
    kind: str
    rows: tuple[ReviewRow, ...]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class HeldRow:
    document_id: str
    title: str
    reasons: tuple[HoldReason, ...]
    published_at: datetime | None  # when the version the assistant still sees was published; None: never
    held_since: datetime


@dataclass(frozen=True)
class HeldPage:
    check: str | None  # the filter; None: every held document
    rows: tuple[HeldRow, ...]
    counts: tuple[tuple[str, int], ...]  # documents held by each check, zero included
    total: int
    page: int
    pages: int


HELD_CHECKS = tuple(check.value for check in Check)


@dataclass(frozen=True)
class DocumentRow:
    id: str
    citation: str
    title: str
    issuer: str
    kind: str
    status: str
    suppressed: bool


@dataclass(frozen=True)
class CorrectionRow:
    value: Any
    source_value: Any
    reason: str
    author: str
    created_at: datetime


@dataclass(frozen=True)
class SearchFilters:
    issuer: str | None = None
    family: str | None = None
    year: int | None = None
    status: str | None = None  # the effective status: the published one, else the registry's
    state: str | None = None  # one of STATES


@dataclass(frozen=True)
class DocumentHit:
    id: str
    citation: str
    title: str
    issuer: str
    family: str
    number: str
    year: int | None
    kind: str
    status: str
    state: str


@dataclass(frozen=True)
class ArticleHit:
    """A published article whose wording matches: the unit lawyers cite, not each of its paragraphs."""

    document_id: str
    citation: str
    title: str
    address: str
    label: str
    heading: str | None
    excerpt: str  # the matching words between « and »
    status: str


@dataclass(frozen=True)
class Facet:
    name: str  # one of FACETS
    values: tuple[tuple[str, int], ...]  # each value, with the matching documents the other filters leave


@dataclass(frozen=True)
class SearchPage:
    query: str
    kind: str  # one of SEARCH_KINDS: the list on this page
    filters: SearchFilters
    documents: tuple[DocumentHit, ...]  # when kind is documents
    articles: tuple[ArticleHit, ...]  # when kind is articles
    documents_total: int
    articles_total: int
    facets: tuple[Facet, ...]
    page: int
    pages: int


@dataclass(frozen=True)
class SeriesRow:
    """An issuer's family of instruments (OJK's POJK, BI's PADG …): what the registry holds of it."""

    issuer: str
    family: str
    documents: int
    first_year: int | None
    last_year: int | None


@dataclass(frozen=True)
class SeriesPage:
    issuer: str
    family: str
    years: tuple[tuple[int, int], ...]  # each year held, newest first, with its documents
    year: int | None  # the year shown: the one asked for, else the newest
    documents: tuple[DocumentHit, ...]  # that year's, by number


@dataclass(frozen=True)
class FieldRow:
    """One overridable field: what the knowledge layer sees, the registry's value, and each source's."""

    field: str
    effective: Any
    registry: Any
    by_source: tuple[tuple[str, Any], ...]  # (connector, value)
    correction: CorrectionRow | None


@dataclass(frozen=True)
class SourceRow:
    connector: str
    source_id: str
    url: str
    fetched_at: datetime
    missing_since: datetime | None


@dataclass(frozen=True)
class CuratorNote:
    reason: str
    author: str
    created_at: datetime


@dataclass(frozen=True)
class ContentRow:
    sha256: str
    label: str  # a file's role, a text's language
    media_type: str
    detail: str  # pages; a text's origin and method
    problems: tuple[str, ...] = ()  # a text's structure problems
    approval: CuratorNote | None = None  # a curator's approval of exactly these problems
    correction: CuratorNote | None = None  # a curator's correction of the text's wording, in effect
    editable: bool = False  # a current main text: the kind a curator may correct


@dataclass(frozen=True)
class ProvisionRow:
    address: str
    kind: str
    label: str
    heading: str | None
    depth: int
    page_start: int | None
    valid_to: date | None


@dataclass(frozen=True)
class LinkRow:
    type: str
    document_id: str  # the other end
    document_title: str | None  # None when the other end isn't held
    from_address: str | None
    to_address: str | None
    method: str
    document_citation: str | None = None  # None when the other end isn't held
    effective_on: date | None = None  # when the changing document (the link's source) takes effect


@dataclass(frozen=True)
class CitationRow:
    id: int
    relation: str
    target_text: str
    target_id: str | None
    from_address: str | None


@dataclass(frozen=True)
class ConflictRow:
    id: int
    field: str
    correction: Any
    source_value: Any
    detected_at: datetime


@dataclass(frozen=True)
class StatusRow:
    address: str | None
    status: str
    effective_from: date | None
    source: str
    caused_by: str | None = None  # the document whose link implies it (source "links")
    caused_by_citation: str | None = None


@dataclass(frozen=True)
class SuppressionRow:
    reason: str
    author: str
    created_at: datetime


@dataclass(frozen=True)
class DocumentView:
    summary: DocumentRow
    id_confidence: str
    fields: tuple[FieldRow, ...]
    suppression: SuppressionRow | None
    sources: tuple[SourceRow, ...]
    files: tuple[ContentRow, ...]
    texts: tuple[ContentRow, ...]
    provisions: tuple[ProvisionRow, ...]  # the first main text's, up to a limit
    provisions_total: int
    links_out: tuple[LinkRow, ...]
    links_in: tuple[LinkRow, ...]
    open_citations: tuple[CitationRow, ...]  # not linked: the target isn't held, or nothing names it
    conflicts: tuple[ConflictRow, ...]
    status_history: tuple[StatusRow, ...]
    open_reviews: tuple[ReviewRow, ...]
    hold: tuple[HoldReason, ...] = ()  # why the publish gate holds it back; empty when it passes
    published_at: datetime | None = None  # the version the assistant sees; None: not published
    lapsed_corrections: tuple[str, ...] = ()  # texts corrected before the source replaced them (their sha256)


@dataclass(frozen=True)
class EditableText:
    """A current main text, to correct: its effective wording is at `storage_key`."""

    document_id: str
    citation: str
    sha256: str  # the source text's
    storage_key: str
    paged: bool
    corrected: bool  # the wording at `storage_key` is a curator's correction already


@dataclass(frozen=True)
class CorrectionView:
    """A curator's correction of a text (the latest one), to compare with the source's wording."""

    document_id: str
    citation: str
    sha256: str  # the source text's
    source_storage_key: str
    corrected_storage_key: str
    note: CuratorNote
    active: bool  # not withdrawn
    current: bool  # the text it corrects is still the source's current one: the correction applies


@dataclass(frozen=True)
class ProvisionChange:
    """Another document's change to a provision: an amendment or a revocation, and where the new wording is."""

    type: str  # amends, partly_revokes, revokes
    document_id: str  # the changing document
    citation: str | None  # None when it isn't held
    effective_on: date | None  # when it takes effect
    new_address: str | None  # where the changing document words the article now (pasal-i/pasal-115), if it does


@dataclass(frozen=True)
class SourceProvision:
    """A provision as the parser cut it from a text: what a reading is made from."""

    address: str
    parent_address: str | None
    kind: str
    label: str
    heading: str | None
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    valid_to: date | None
    changes: tuple[ProvisionChange, ...] = ()


@dataclass(frozen=True)
class ReadableText:
    sha256: str
    language: str
    detail: str  # its origin and method
    main: bool  # a main text: the regulation's own, the kind a curator may correct


@dataclass(frozen=True)
class ReadingSource:
    """A current text with provisions, and where its effective wording (the source's, or a correction) is."""

    document_id: str
    citation: str
    title: str
    sha256: str
    storage_key: str
    problems: tuple[str, ...]  # its structure problems
    corrected: bool  # the wording at `storage_key` is a curator's correction
    editable: bool
    pdf_sha256: str | None  # the document's main file, when it is a PDF: to read beside the text
    texts: tuple[ReadableText, ...]  # every current text of the document that has provisions
    provisions: tuple[SourceProvision, ...]  # in reading order


@dataclass(frozen=True)
class ReadingProvision:
    address: str
    parent_address: str | None
    kind: str
    label: str
    heading: str | None
    depth: int
    part: int  # the part of the reading its first passage is in
    page_start: int | None
    page_end: int | None
    valid_to: date | None
    changes: tuple[ProvisionChange, ...]
    edit_from: int  # where an editor finds it, in UTF-16 units (as the browser counts)
    edit_to: int


@dataclass(frozen=True)
class PassageReference:
    """A reference in a block to another provision of the same text ("Pasal 19 ayat (2)")."""

    start: int  # where it is in the block's text, in UTF-16 units (as the browser counts)
    end: int
    address: str


@dataclass(frozen=True)
class PageStart:
    at: int  # where in the block's text the page's first word is, in UTF-16 units
    page: int  # of the official file


@dataclass(frozen=True)
class ReadingBlock:
    """A paragraph or a list item of a passage, its printed lines joined (domain/layout.py)."""

    text: str
    marker: str | None = None  # a list item's number: "(1)", "a.", "16."
    depth: int = 0  # a list item's nesting, from 0
    pages: tuple[PageStart, ...] = ()
    references: tuple[PassageReference, ...] = ()


@dataclass(frozen=True)
class ReadingPassage:
    address: str | None  # None: text outside every provision (a title, a closing)
    opens: bool  # the provision's first passage: where its heading goes
    titled: bool  # its heading lines were taken off the text: show the label and heading instead
    blocks: tuple[ReadingBlock, ...] = ()  # its wording, laid out for reading


@dataclass(frozen=True)
class TextReading:
    """One part of a text, read as the parser cut it, with the whole text's outline."""

    document_id: str
    citation: str
    title: str
    sha256: str
    problems: tuple[str, ...]
    corrected: bool
    editable: bool
    pdf_sha256: str | None
    texts: tuple[ReadableText, ...]
    part: int
    parts: int
    provisions: tuple[ReadingProvision, ...]  # all of them: the outline
    passages: tuple[ReadingPassage, ...]  # this part's


@dataclass(frozen=True)
class StoredBytes:
    storage_key: str
    media_type: str
    name: str


class CurationViews(Protocol):
    def dashboard(self) -> Dashboard: ...

    def review_page(self, kind: str, page: int) -> ReviewPage: ...

    def held_page(self, check: str | None, page: int) -> HeldPage:
        """Held documents, those whose last good version is still published first."""

    def search(self, query: str, filters: SearchFilters, kind: str, page: int) -> SearchPage:
        """Documents whose metadata or published wording matches `query` (every document when it is empty),
        filtered, with each facet's counts; and the matching articles."""

    def series(self) -> tuple[SeriesRow, ...]: ...

    def series_page(self, issuer: str, family: str, year: int | None) -> SeriesPage | None:
        """None if the registry holds nothing of the series."""

    def document(self, document_id: str) -> DocumentView | None: ...

    def editable_text(self, document_id: str, sha256: str) -> EditableText | None:
        """None unless `sha256` is a current main text of the document."""

    def correction(self, document_id: str, sha256: str) -> CorrectionView | None:
        """The latest correction of the document's text `sha256`, current or not; None if it has none."""

    def stored(self, document_id: str, sha256: str) -> StoredBytes | None:
        """A file or text of the document, to stream to the curator; None if it isn't the document's."""

    def exists(self, document_id: str) -> bool: ...

    def reading_source(self, document_id: str, sha256: str | None) -> ReadingSource | None:
        """A current text of the document that has provisions: `sha256`, or the main one when None."""
