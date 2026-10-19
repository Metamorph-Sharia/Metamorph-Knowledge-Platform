"""Curation read models and services in memory, for the curation API's tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from metamorph_platform.application.views import (
    CheckRow,
    CitationRow,
    ContentRow,
    CorrectionView,
    CuratorNote,
    Dashboard,
    DocumentRow,
    DocumentView,
    EditableText,
    FieldRow,
    HeldPage,
    HeldRow,
    ReviewPage,
    ReviewRow,
    SourceRow,
    StoredBytes,
)
from metamorph_platform.domain.gate import Check, HoldReason

NOW = datetime(2026, 10, 15, 4, 36, tzinfo=UTC)
DOC = "ojk:pojk:2019:10"
ROW = DocumentRow(
    DOC,
    "POJK 10/POJK.05/2019",
    "Penyelenggaraan Usaha Pembiayaan Syariah",
    "ojk",
    "regulation",
    "in_force",
    suppressed=False,
)
TEXT_SHA = "a" * 64
GAPPY_SHA = "b" * 64
GAP = HoldReason(Check.STRUCTURE, "Pasal 3 missing")
GAPPY_TEXT = "Pasal 1\nSatu.\nPasal 3\nTiga.\n"
FIXED_TEXT = "Pasal 1\nSatu.\nPasal 2\nDua.\nPasal 3\nTiga.\n"


class MemoryViews:
    def dashboard(self) -> Dashboard:
        return Dashboard(
            "ok",
            NOW,
            (CheckRow("ojk", "ok", "last loaded 2 h ago (every 24 h)"),),
            (("ojk", 973),),
            2524,
            (("unresolved_citation", 235), ("conflict", 0)),
            (),
            held=95,
            held_published=4,
        )

    def held_page(self, check: str | None, page: int) -> HeldPage:
        rows = (HeldRow(DOC, ROW.title, (GAP,), published_at=NOW, held_since=NOW),)
        counts = tuple((c.value, 1 if c is Check.STRUCTURE else 0) for c in Check)
        shown = rows if check in (None, "structure") else ()
        return HeldPage(check, shown, counts, len(shown), 1, 1)

    def review_page(self, kind: str, page: int) -> ReviewPage:
        summary = "Keputusan Presiden Nomor 84/P"
        rows = (ReviewRow(12, kind, NOW, DOC, ROW.title, summary, {"document_id": DOC, "target_text": summary}),)
        citations = kind == "unresolved_citation"
        return ReviewPage(kind, rows if citations else (), 1 if citations else 0, 1, 1)

    def search(self, query: str, limit: int) -> list[DocumentRow]:
        return [ROW] if "10" in query else []

    def document(self, document_id: str) -> DocumentView | None:
        if document_id != DOC:
            return None
        fields = (FieldRow("effective_on", date(2019, 2, 27), None, (("ojk", None),), None),)
        sources = (SourceRow("ojk", "regalert:abc", "https://regalert.today/document/abc", NOW, None),)
        return DocumentView(
            ROW,
            "high",
            fields,
            None,
            sources,
            (),
            (
                ContentRow(TEXT_SHA, "id", "text/markdown", "source text"),
                ContentRow(GAPPY_SHA, "id", "text/markdown", "source text", ("Pasal 3 missing",), editable=True),
                ContentRow(
                    "c" * 64,
                    "id",
                    "text/markdown",
                    "source text",
                    ("Pasal 9 missing",),
                    CuratorNote("Pasal 9 dicabut", "ani", NOW),
                    correction=CuratorNote("PDF hal. 4", "ani", NOW),
                    editable=True,
                ),
            ),
            (),
            0,
            (),
            (),
            (CitationRow(88, "legal_basis", "Undang-Undang Nomor 21 Tahun 2011", None, None),),
            (),
            (),
            (),
            hold=(GAP,),
            published_at=NOW,
            lapsed_corrections=("d" * 64,),
        )

    def editable_text(self, document_id: str, sha256: str) -> EditableText | None:
        if (document_id, sha256) != (DOC, GAPPY_SHA):
            return None
        return EditableText(DOC, ROW.citation, GAPPY_SHA, "blobs/bb/gappy", paged=False, corrected=False)

    def correction(self, document_id: str, sha256: str) -> CorrectionView | None:
        if sha256 != "c" * 64:
            return None
        return CorrectionView(DOC, ROW.citation, sha256, "blobs/bb/gappy", "blobs/cc/fixed",
                              CuratorNote("PDF hal. 4", "ani", NOW), active=True, current=True)  # fmt: skip

    def stored(self, document_id: str, sha256: str) -> StoredBytes | None:
        return (
            StoredBytes("blobs/aa/text", "text/markdown; charset=utf-8", "id-aaaa.md") if sha256 == TEXT_SHA else None
        )

    def exists(self, document_id: str) -> bool:
        return document_id == DOC


class CountingParse:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, everything: bool = False):
        self.runs += 1


class CountingPublish:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, everything: bool = False):
        self.runs += 1
