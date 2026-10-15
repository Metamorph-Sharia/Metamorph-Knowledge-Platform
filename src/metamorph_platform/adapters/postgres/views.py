"""PostgreSQL queries behind the curation pages (application/views.py). Read-only."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from metamorph_platform.application.views import (
    PAGE_SIZE,
    REVIEW_KINDS,
    BundleRow,
    CheckRow,
    CitationRow,
    ConflictRow,
    ContentRow,
    CorrectionRow,
    Dashboard,
    DocumentRow,
    DocumentView,
    FieldRow,
    LinkRow,
    ProvisionRow,
    ReviewPage,
    ReviewRow,
    SourceRow,
    StatusRow,
    StoredBytes,
    SuppressionRow,
)
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
        return Dashboard(
            health_status=health["status"] if health else None,
            health_taken_at=health["taken_at"] if health else None,
            checks=tuple(CheckRow(**check) for check in health["checks"]) if health else (),
            documents_by_issuer=documents_by_issuer,
            published=published,
            open_reviews=tuple((kind, open_counts.get(kind, 0)) for kind in REVIEW_KINDS),
            recent_bundles=tuple(BundleRow(**row) for row in bundles),
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
        if kind == "structure_suspect":
            problems = subject.get("problems", [])
            more = len(problems) - PROBLEMS_SHOWN
            return "; ".join(problems[:PROBLEMS_SHOWN]) + (f"; and {more} more" if more > 0 else "")
        if kind == "unresolved_citation":
            return f"Cites “{subject.get('target_text', '')}”, which names no document"
        if kind == "unresolved_id":
            return "The connector couldn't tell which document this is"
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
        )

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
        rows = self.connection.execute(
            "SELECT sha256, language, origin, method, structure_problems FROM registry.text_version "
            "WHERE document_id = %s AND is_current ORDER BY language, id",
            (document_id,),
        )
        return tuple(
            ContentRow(
                sha,
                language,
                TEXT_MEDIA_TYPE,
                f"{origin.replace('_', ' ')}, {method.replace('_', ' ')}",
                tuple(problems or ()),
            )
            for sha, language, origin, method, problems in rows
        )

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


def _at(received: dict, path: str) -> Any:
    value: Any = received
    for key in path.strip("{}").split(","):
        value = value.get(key) if isinstance(value, dict) else None
    return value
