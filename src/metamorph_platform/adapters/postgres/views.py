"""PostgreSQL queries behind the curation pages (application/views.py). Read-only."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from metamorph_platform.adapters.postgres.derived import MAIN_TEXT
from metamorph_platform.application.views import (
    HELD_CHECKS,
    PAGE_SIZE,
    REVIEW_KINDS,
    BundleRow,
    CheckRow,
    CitationRow,
    ConflictRow,
    ContentRow,
    CorrectionRow,
    CorrectionView,
    CuratorNote,
    Dashboard,
    DocumentRow,
    DocumentView,
    EditableText,
    FieldRow,
    HeldPage,
    HeldRow,
    LinkRow,
    ProvisionRow,
    ReviewPage,
    ReviewRow,
    SourceRow,
    StatusRow,
    StoredBytes,
    SuppressionRow,
)
from metamorph_platform.domain.gate import Check, HoldReason
from metamorph_platform.domain.loading import TEXT_MEDIA_TYPE

PROVISIONS_SHOWN = 400
PROBLEMS_SHOWN = 3
# Each overridable field, and where a source's own document (registry.document_source.received) states it.
FIELDS = (
    ("citation", "{document,citation}"),
    ("title", "{document,title}"),
    ("kind", "{document,kind}"),
    ("status", "{document,status,value}"),
    ("status_as_of", "{document,status,as_of}"),
    ("year", "{document,year}"),
    ("enacted_on", "{document,dates,enacted}"),
    ("promulgated_on", "{document,dates,promulgated}"),
    ("effective_on", "{document,dates,effective}"),
)
_DOCUMENT_ROW = """
SELECT d.id, d.citation, d.title, d.issuer, d.kind, d.status, s.document_id IS NOT NULL AS suppressed
FROM registry.document d LEFT JOIN curation.suppression s ON s.document_id = d.id
"""
# The document a review item is about: named in its subject, or through the correction a conflict is about.
_REVIEW_ROWS = """
SELECT r.id, r.kind, r.created_at, r.subject, d.id AS document_id, d.title AS document_title
FROM curation.review_item r
LEFT JOIN curation.override o ON o.id = (r.subject ->> 'override_id')::bigint
LEFT JOIN registry.document d ON d.id = coalesce(r.subject ->> 'document_id', o.document_id)
"""
# The active correction of a text (alias t), if any: `c` in what follows.
_CORRECTION = (
    "LEFT JOIN curation.text_correction c ON c.document_id = t.document_id AND c.corrects_sha256 = t.sha256 "
    "AND c.active"
)
# Held documents, filtered by one check (or none); those whose last good version is still published first.
_HELD_ROWS = """
SELECT h.document_id, d.title, h.reasons, p.published_at, h.held_since
FROM registry.hold h JOIN registry.document d ON d.id = h.document_id
LEFT JOIN published.document p ON p.id = h.document_id
WHERE %(check)s::text IS NULL OR h.reasons @> jsonb_build_array(jsonb_build_object('check', %(check)s::text))
"""


class PostgresCurationViews:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # --- dashboard and queues ----------------------------------------------------------------------

    def dashboard(self) -> Dashboard:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            health = cursor.execute(
                "SELECT status, taken_at, checks FROM ingest.health_snapshot ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
            open_counts = dict(
                (row["kind"], row["count"])
                for row in cursor.execute(
                    "SELECT kind, count(*) FROM curation.review_item WHERE state = 'open' GROUP BY kind"
                )
            )
            bundles = cursor.execute(
                "SELECT connector, run_id, state, received_at, loaded, unchanged, quarantined FROM ingest.bundle "
                "ORDER BY received_at DESC LIMIT 8"
            ).fetchall()
            issuers = cursor.execute("SELECT issuer, count(*) FROM registry.document GROUP BY 1 ORDER BY 2 DESC")
            documents_by_issuer = tuple((row["issuer"], row["count"]) for row in issuers)
            (published,) = self.connection.execute("SELECT count(*) FROM published.document").fetchone()
            held, held_published = self.connection.execute(
                "SELECT count(*), count(p.id) FROM registry.hold h "
                "LEFT JOIN published.document p ON p.id = h.document_id"
            ).fetchone()
        return Dashboard(
            health_status=health["status"] if health else None,
            health_taken_at=health["taken_at"] if health else None,
            checks=tuple(CheckRow(**check) for check in health["checks"]) if health else (),
            documents_by_issuer=documents_by_issuer,
            published=published,
            open_reviews=tuple((kind, open_counts.get(kind, 0)) for kind in REVIEW_KINDS),
            recent_bundles=tuple(BundleRow(**row) for row in bundles),
            held=held,
            held_published=held_published,
        )

    def held_page(self, check: str | None, page: int) -> HeldPage:
        by_check = dict(
            self.connection.execute(
                "SELECT reason ->> 'check', count(DISTINCT h.document_id) "
                "FROM registry.hold h, jsonb_array_elements(h.reasons) reason GROUP BY 1"
            ).fetchall()
        )
        (total,) = self.connection.execute(f"SELECT count(*) FROM ({_HELD_ROWS}) held", {"check": check}).fetchone()
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(max(page, 1), pages)
        rows = self.connection.execute(
            _HELD_ROWS + " ORDER BY p.id IS NULL, h.held_since, h.document_id LIMIT %(limit)s OFFSET %(offset)s",
            {"check": check, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
        )
        return HeldPage(
            check=check,
            rows=tuple(
                HeldRow(document_id, title, _hold_reasons(reasons), published_at, held_since)
                for document_id, title, reasons, published_at, held_since in rows
            ),
            counts=tuple((name, by_check.get(name, 0)) for name in HELD_CHECKS),
            total=total,
            page=page,
            pages=pages,
        )

    def review_page(self, kind: str, page: int) -> ReviewPage:
        (total,) = self.connection.execute(
            "SELECT count(*) FROM curation.review_item WHERE kind = %s AND state = 'open'", (kind,)
        ).fetchone()
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(max(page, 1), pages)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                _REVIEW_ROWS + " WHERE r.kind = %s AND r.state = 'open' ORDER BY r.created_at, r.id LIMIT %s OFFSET %s",
                (kind, PAGE_SIZE, (page - 1) * PAGE_SIZE),
            ).fetchall()
        return ReviewPage(kind, tuple(self._review_row(row) for row in rows), total, page, pages)

    def _review_row(self, row: dict) -> ReviewRow:
        return ReviewRow(
            id=row["id"],
            kind=row["kind"],
            created_at=row["created_at"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            summary=self._summary(row["kind"], row["subject"]),
            subject=row["subject"],
        )

    def _summary(self, kind: str, subject: dict) -> str:
        if kind == "unresolved_citation":
            return f"Cites “{subject.get('target_text', '')}”, which names no document"
        if kind == "quarantine":
            row = self.connection.execute(
                "SELECT problems FROM ingest.quarantine WHERE bundle_id = %s AND line = %s",
                (subject.get("bundle_id"), subject.get("line")),
            ).fetchone()
            problems = "; ".join(row[0][:PROBLEMS_SHOWN]) if row else "the line is no longer in the quarantine"
            return f"Bundle {subject.get('bundle_id')}, line {subject.get('line')}: {problems}"
        if kind == "conflict":
            row = self.connection.execute(
                "SELECT o.field, o.value, c.source_value FROM curation.override o "
                "LEFT JOIN curation.conflict c ON c.override_id = o.id AND c.state = 'open' WHERE o.id = %s",
                (subject.get("override_id"),),
            ).fetchone()
            if row:
                return f"{row[0]}: corrected to “{row[1]}”, the source now says “{row[2]}”"
        return ""

    # --- documents -------------------------------------------------------------------------------

    def search(self, query: str, limit: int) -> list[DocumentRow]:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.connection.execute(
            _DOCUMENT_ROW
            + """
            WHERE d.id ILIKE %(p)s OR d.citation ILIKE %(p)s OR d.title ILIKE %(p)s
               OR EXISTS (SELECT 1 FROM registry.alias a WHERE a.document_id = d.id AND a.text ILIKE %(p)s)
            ORDER BY (lower(d.id) = lower(%(q)s)) DESC, d.issuer, d.year DESC NULLS LAST, d.id
            LIMIT %(limit)s
            """,
            {"p": pattern, "q": query, "limit": limit},
        )
        return [DocumentRow(*row) for row in rows]

    def exists(self, document_id: str) -> bool:
        return (
            self.connection.execute("SELECT 1 FROM registry.document WHERE id = %s", (document_id,)).fetchone()
            is not None
        )

    def document(self, document_id: str) -> DocumentView | None:
        summary = self.connection.execute(_DOCUMENT_ROW + " WHERE d.id = %s", (document_id,)).fetchone()
        if summary is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            registry = cursor.execute("SELECT * FROM registry.document WHERE id = %s", (document_id,)).fetchone()
            published = cursor.execute("SELECT * FROM published.document WHERE id = %s", (document_id,)).fetchone()
            suppression = cursor.execute(
                "SELECT reason, author, created_at FROM curation.suppression WHERE document_id = %s", (document_id,)
            ).fetchone()
            sources = cursor.execute(
                "SELECT connector, source_id, url, fetched_at, missing_since, received FROM registry.document_source "
                "WHERE document_id = %s ORDER BY connector, source_id",
                (document_id,),
            ).fetchall()
            corrections = {
                row["field"]: CorrectionRow(
                    row["value"], row["source_value"], row["reason"], row["author"], row["created_at"]
                )
                for row in cursor.execute(
                    "SELECT field, value, source_value, reason, author, created_at FROM curation.override "
                    "WHERE document_id = %s AND active",
                    (document_id,),
                )
            }
        provisions, provisions_total = self._provisions(document_id)
        return DocumentView(
            summary=DocumentRow(*summary),
            id_confidence=registry["id_confidence"],
            fields=tuple(
                FieldRow(
                    field=name,
                    effective=(published or registry).get(name),
                    registry=registry.get(name),
                    by_source=tuple((s["connector"], _at(s["received"], path)) for s in sources),
                    correction=corrections.get(name),
                )
                for name, path in FIELDS
            ),
            suppression=SuppressionRow(**suppression) if suppression else None,
            sources=tuple(SourceRow(**{k: v for k, v in s.items() if k != "received"}) for s in sources),
            files=self._files(document_id),
            texts=self._texts(document_id),
            provisions=provisions,
            provisions_total=provisions_total,
            links_out=self._links(document_id, outgoing=True),
            links_in=self._links(document_id, outgoing=False),
            open_citations=tuple(
                CitationRow(*row)
                for row in self.connection.execute(
                    "SELECT id, relation, target_text, target_id, from_address FROM registry.citation "
                    "WHERE document_id = %s AND link_id IS NULL ORDER BY id",
                    (document_id,),
                )
            ),
            conflicts=tuple(
                ConflictRow(*row)
                for row in self.connection.execute(
                    "SELECT c.id, o.field, o.value, c.source_value, c.detected_at FROM curation.conflict c "
                    "JOIN curation.override o ON o.id = c.override_id WHERE o.document_id = %s AND c.state = 'open'",
                    (document_id,),
                )
            ),
            status_history=tuple(
                StatusRow(*row)
                for row in self.connection.execute(
                    "SELECT address, status, effective_from, source FROM registry.status_event WHERE document_id = %s "
                    "ORDER BY effective_from NULLS FIRST, recorded_at",
                    (document_id,),
                )
            ),
            open_reviews=self._open_reviews(document_id),
            hold=self._hold(document_id),
            published_at=published["published_at"] if published else None,
            lapsed_corrections=tuple(
                sha
                for (sha,) in self.connection.execute(
                    "SELECT c.corrects_sha256 FROM curation.text_correction c WHERE c.document_id = %s AND c.active "
                    "AND NOT EXISTS (SELECT 1 FROM registry.text_version t WHERE t.document_id = c.document_id "
                    "AND t.sha256 = c.corrects_sha256 AND t.is_current) ORDER BY c.created_at",
                    (document_id,),
                )
            ),
        )

    def editable_text(self, document_id: str, sha256: str) -> EditableText | None:
        row = self.connection.execute(
            "SELECT d.citation, coalesce(c.storage_key, b.storage_key), t.paged, c.id IS NOT NULL "
            "FROM registry.text_version t JOIN registry.document d ON d.id = t.document_id "
            f"JOIN registry.blob b ON b.sha256 = t.sha256 {_CORRECTION} "
            f"WHERE t.document_id = %s AND t.sha256 = %s AND t.is_current AND {MAIN_TEXT}",
            (document_id, sha256),
        ).fetchone()
        if row is None:
            return None
        citation, storage_key, paged, corrected = row
        return EditableText(document_id, citation, sha256, storage_key, paged, corrected)

    def correction(self, document_id: str, sha256: str) -> CorrectionView | None:
        row = self.connection.execute(
            """
            SELECT d.citation, b.storage_key, c.storage_key, c.reason, c.author, c.created_at, c.active,
                   EXISTS (SELECT 1 FROM registry.text_version t
                           WHERE t.document_id = c.document_id AND t.sha256 = c.corrects_sha256 AND t.is_current)
            FROM curation.text_correction c JOIN registry.document d ON d.id = c.document_id
            JOIN registry.blob b ON b.sha256 = c.corrects_sha256
            WHERE c.document_id = %s AND c.corrects_sha256 = %s
            ORDER BY c.id DESC LIMIT 1
            """,
            (document_id, sha256),
        ).fetchone()
        if row is None:
            return None
        citation, source_key, corrected_key, reason, author, created_at, active, current = row
        note = CuratorNote(reason, author, created_at)
        return CorrectionView(document_id, citation, sha256, source_key, corrected_key, note, active, current)

    def stored(self, document_id: str, sha256: str) -> StoredBytes | None:
        row = self.connection.execute(
            """
            SELECT b.storage_key, b.media_type, coalesce(f.title, f.role || '-' || left(f.sha256, 12)) AS name
            FROM registry.document_file f JOIN registry.blob b USING (sha256)
            WHERE f.document_id = %(d)s AND f.sha256 = %(s)s
            UNION ALL
            SELECT b.storage_key, %(text)s, t.language || '-' || left(t.sha256, 12) || '.md'
            FROM registry.text_version t JOIN registry.blob b USING (sha256)
            WHERE t.document_id = %(d)s AND t.sha256 = %(s)s
            UNION ALL
            SELECT c.storage_key, %(text)s, 'corrected-' || left(c.sha256, 12) || '.md'
            FROM curation.text_correction c
            WHERE c.document_id = %(d)s AND c.sha256 = %(s)s
            LIMIT 1
            """,
            {"d": document_id, "s": sha256, "text": TEXT_MEDIA_TYPE},
        ).fetchone()
        return StoredBytes(*row) if row else None

    # --- parts of the document page ---------------------------------------------------------------

    def _files(self, document_id: str) -> tuple[ContentRow, ...]:
        rows = self.connection.execute(
            "SELECT f.sha256, f.role, b.media_type, f.pages FROM registry.document_file f "
            "JOIN registry.blob b USING (sha256) WHERE f.document_id = %s ORDER BY f.role, f.sha256",
            (document_id,),
        )
        return tuple(
            ContentRow(sha, role, media, f"{pages} pages" if pages else "") for sha, role, media, pages in rows
        )

    def _texts(self, document_id: str) -> tuple[ContentRow, ...]:
        """Each current text, with its correction if any, and its approval while it covers exactly the problems
        its effective content (the correction's, or its own) has now."""
        rows = self.connection.execute(
            f"""
            SELECT t.sha256, t.language, t.origin, t.method, t.structure_problems,
                   a.reason, a.author, a.created_at, c.reason, c.author, c.created_at, {MAIN_TEXT} AS editable
            FROM registry.text_version t {_CORRECTION}
            LEFT JOIN curation.approval a ON a.document_id = t.document_id
                 AND a.text_sha256 = coalesce(c.sha256, t.sha256) AND a.active AND a.problems = t.structure_problems
            WHERE t.document_id = %s AND t.is_current ORDER BY t.language, t.id
            """,
            (document_id,),
        )
        return tuple(
            ContentRow(
                sha,
                language,
                TEXT_MEDIA_TYPE,
                f"{origin.replace('_', ' ')}, {method.replace('_', ' ')}",
                tuple(problems or ()),
                CuratorNote(approved_why, approved_by, approved_at) if approved_why else None,
                CuratorNote(corrected_why, corrected_by, corrected_at) if corrected_why else None,
                editable,
            )
            for (sha, language, origin, method, problems, approved_why, approved_by, approved_at, corrected_why,
                 corrected_by, corrected_at, editable) in rows
        )  # fmt: skip

    def _hold(self, document_id: str) -> tuple[HoldReason, ...]:
        row = self.connection.execute("SELECT reasons FROM registry.hold WHERE document_id = %s", (document_id,))
        found = row.fetchone()
        return _hold_reasons(found[0]) if found else ()

    def _provisions(self, document_id: str) -> tuple[tuple[ProvisionRow, ...], int]:
        """The first current text's tree: the one the parser read first (the main Indonesian text)."""
        rows = self.connection.execute(
            """
            SELECT p.address, p.kind, p.label, p.heading, p.parent_address, p.page_start, p.valid_to
            FROM registry.provision p
            WHERE p.text_version_id = (SELECT min(t.id) FROM registry.text_version t
                                       JOIN registry.provision q ON q.text_version_id = t.id
                                       WHERE t.document_id = %s AND t.is_current)
            ORDER BY p.ordinal
            """,
            (document_id,),
        ).fetchall()
        depth: dict[str, int] = {}
        tree = []
        for address, kind, label, heading, parent, page_start, valid_to in rows:
            depth[address] = depth.get(parent, -1) + 1 if parent else 0
            tree.append(ProvisionRow(address, kind, label, heading, depth[address], page_start, valid_to))
        return tuple(tree[:PROVISIONS_SHOWN]), len(tree)

    def _links(self, document_id: str, *, outgoing: bool) -> tuple[LinkRow, ...]:
        here, there = ("from_document", "to_document") if outgoing else ("to_document", "from_document")
        rows = self.connection.execute(
            f"SELECT l.type, l.{there}, d.title, l.from_address, l.to_address, l.method FROM registry.link l "
            f"LEFT JOIN registry.document d ON d.id = l.{there} WHERE l.{here} = %s ORDER BY l.type, l.{there}",
            (document_id,),
        )
        return tuple(LinkRow(*row) for row in rows)

    def _open_reviews(self, document_id: str) -> tuple[ReviewRow, ...]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                _REVIEW_ROWS + " WHERE r.state = 'open' AND d.id = %s ORDER BY r.created_at", (document_id,)
            ).fetchall()
        return tuple(self._review_row(row) for row in rows)


def _hold_reasons(stored: list[dict]) -> tuple[HoldReason, ...]:
    return tuple(HoldReason(Check(reason["check"]), reason["detail"]) for reason in stored)


def _at(received: dict, path: str) -> Any:
    value: Any = received
    for key in path.strip("{}").split(","):
        value = value.get(key) if isinstance(value, dict) else None
    return value
