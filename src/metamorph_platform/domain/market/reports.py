"""Reports cut into passages with their pages: the unit to read, cite and embed (market-data-layer-plan.md, Phase 4).

A report's chapters can't be found alike across editions (Step 0b), so a report is cut by one rule for all:
- paragraphs are what metamorph-pdf-text wrote, separated by blank lines, in reading order across pages;
- a passage gathers paragraphs until it reaches MIN_WORDS, and never passes MAX_WORDS. A longer paragraph, usually
  a table, is split at its line ends, and a longer line by words;
- a short tail joins the passage before it when the two fit.
A report has no legal force: it says what a regulator reports or plans, never a rule.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from metamorph_contract import split_pages
from metamorph_market import ReportRecord

MIN_WORDS, MAX_WORDS = 250, 400
ISSUERS = {"ojk": "Otoritas Jasa Keuangan", "bi": "Bank Indonesia"}  # how a citation names the issuer


@dataclass(frozen=True)
class Passage:
    ordinal: int
    page_start: int
    page_end: int
    text: str
    words: int

    @property
    def address(self) -> str:
        return f"p-{self.ordinal}"


@dataclass(frozen=True)
class _Piece:
    page: int
    text: str
    words: int


def passages(text: str) -> tuple[Passage, ...]:
    gathered: list[list[_Piece]] = []
    current: list[_Piece] = []
    for piece in _pieces(text):
        if current and _words(current) + piece.words > MAX_WORDS:
            gathered.append(current)
            current = []
        current.append(piece)
        if _words(current) >= MIN_WORDS:
            gathered.append(current)
            current = []
    if current and gathered and _words(gathered[-1]) + _words(current) <= MAX_WORDS:
        gathered[-1] += current
    elif current:
        gathered.append(current)
    return tuple(_passage(ordinal, pieces) for ordinal, pieces in enumerate(gathered, start=1))


def _pieces(text: str) -> Iterator[_Piece]:
    for page, content in split_pages(text):
        for paragraph in content.split("\n\n"):
            for chunk in _within_limit(paragraph.strip()):
                if words := len(chunk.split()):
                    yield _Piece(page, chunk, words)


def _within_limit(paragraph: str) -> list[str]:
    """The paragraph, or its lines packed into chunks of at most MAX_WORDS; a longer line is cut by words."""
    if len(paragraph.split()) <= MAX_WORDS:
        return [paragraph]
    lines = [cut for line in paragraph.splitlines() for cut in _cut_by_words(line)]
    chunks: list[list[str]] = [[]]
    count = 0
    for line in lines:
        words = len(line.split())
        if chunks[-1] and count + words > MAX_WORDS:
            chunks.append([])
            count = 0
        chunks[-1].append(line)
        count += words
    return ["\n".join(chunk) for chunk in chunks]


def _cut_by_words(line: str) -> list[str]:
    words = line.split()
    return [" ".join(words[start : start + MAX_WORDS]) for start in range(0, len(words), MAX_WORDS)] or [""]


def _words(pieces: Sequence[_Piece]) -> int:
    return sum(piece.words for piece in pieces)


def _passage(ordinal: int, pieces: Sequence[_Piece]) -> Passage:
    return Passage(
        ordinal=ordinal,
        page_start=pieces[0].page,
        page_end=pieces[-1].page,
        text="\n\n".join(piece.text for piece in pieces),
        words=_words(pieces),
    )


@dataclass(frozen=True)
class PublishedReport:
    id: str
    issuer: str
    family: str
    edition: str
    title: str
    published_on: str | None
    language: str
    url: str | None  # the page that lists it
    citation: str
    pages: int
    passages: int
    method: str  # text_layer or ocr
    storage_key: str | None  # the PDF in the object store


@dataclass(frozen=True)
class PublishedPassage:
    report: str
    address: str
    ordinal: int
    page_start: int
    page_end: int
    text: str
    words: int


@dataclass(frozen=True)
class Reports:
    reports: tuple[PublishedReport, ...] = ()
    passages: tuple[PublishedPassage, ...] = ()
    held_back: tuple[str, ...] = ()  # reports with no text: material corruption


def reports(records: Sequence[ReportRecord], texts: Mapping[str, str], keys: Mapping[str, str]) -> Reports:
    """`texts`: each report's text by its sha256; `keys`: where each file is kept in the object store."""
    published, cut, held_back = [], [], []
    for record in sorted(records, key=lambda found: found.report.id):
        text = texts.get(record.text.file)
        found = passages(text) if text is not None else ()
        if not found:
            held_back.append(record.report.id)
            continue
        published.append(_published(record, len(found), keys))
        cut += [PublishedPassage(record.report.id, p.address, p.ordinal, p.page_start, p.page_end, p.text, p.words)
                for p in found]
    return Reports(tuple(published), tuple(cut), tuple(held_back))


def _published(record: ReportRecord, passages: int, keys: Mapping[str, str]) -> PublishedReport:
    report = record.report
    return PublishedReport(
        id=report.id,
        issuer=report.issuer,
        family=report.family,
        edition=report.edition,
        title=report.title,
        published_on=report.published_on,
        language=report.language,
        url=record.source.url,
        citation=f"{ISSUERS.get(report.issuer, report.issuer.upper())}, {report.title}",
        pages=record.text.pages,
        passages=passages,
        method=str(record.text.method),
        storage_key=keys.get(record.files[0].sha256),
    )
