"""PostgreSQL queries behind the curation pages (application/views.py). Read-only."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from metamorph_platform.adapters.postgres.derived import MAIN_TEXT, TAKES_EFFECT, TAKING_EFFECT
from metamorph_platform.application.views import (
    FACETS,
    HELD_CHECKS,
    PAGE_SIZE,
    REVIEW_KINDS,
    SEARCH_PAGE_SIZE,
    ArticleHit,
    BundleRow,
    CheckRow,
    CitationRow,
    ConflictRow,
    ContentRow,
    CorrectionRow,
    CorrectionView,
    CuratorNote,
    Dashboard,
    DocumentHit,
    DocumentRow,
    DocumentView,
    EditableText,
    Facet,
    FieldRow,
    GapPage,
    GapRow,
    HeldPage,
    HeldRow,
    LinkRow,
    ProvisionChange,
    ProvisionRow,
    ReadableText,
    ReadingSource,
    ReviewPage,
    ReviewRow,
    SearchFilters,
    SearchPage,
    SeriesPage,
    SeriesRow,
    SourceProvision,
    SourceRow,
    StatusRow,
    StoredBytes,
    SuppressionRow,
)
from metamorph_platform.domain.gate import Check, HoldReason
from metamorph_platform.domain.loading import TEXT_MEDIA_TYPE
from metamorph_platform.domain.publishing import ReviewNote

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
# Every document, as search and browsing list it: its effective status (the published one, else the registry's)
# and whether the assistant sees it.
_HITS = """
SELECT d.id, d.citation, d.title, d.issuer, d.family, d.number, d.year, d.kind, coalesce(pd.status, d.status),
       CASE WHEN s.document_id IS NOT NULL THEN 'suppressed' WHEN h.document_id IS NOT NULL THEN 'held'
            WHEN pd.id IS NOT NULL THEN 'published' ELSE 'unpublished' END
FROM registry.document d
LEFT JOIN curation.suppression s ON s.document_id = d.id
LEFT JOIN registry.hold h ON h.document_id = d.id
LEFT JOIN published.document pd ON pd.id = d.id
"""
_BY_METADATA = """
d.id ILIKE %(p)s OR d.citation ILIKE %(p)s OR d.title ILIKE %(p)s
OR EXISTS (SELECT 1 FROM registry.alias a WHERE a.document_id = d.id AND a.text ILIKE %(p)s)
"""
# Published articles whose wording matches: the units lawyers cite (an article, the considerations, a fatwa's
# ruling), not each paragraph, which its article already holds; and not an amending Pasal I, but the articles
# it words anew.
_ARTICLE_HITS = """
SELECT p.document_id, p.text_sha256, p.address, ts_rank(p.search, q) AS rank
FROM published.provision p CROSS JOIN websearch_to_tsquery('simple', %(q)s) q
LEFT JOIN (SELECT DISTINCT document_id, text_sha256, parent_address FROM published.provision
           WHERE kind = 'pasal' AND parent_address IS NOT NULL) quoted
       ON quoted.document_id = p.document_id AND quoted.text_sha256 = p.text_sha256
      AND quoted.parent_address = p.address
WHERE p.search @@ q AND p.kind <> 'ayat' AND quoted.document_id IS NULL
ORDER BY rank DESC, p.document_id, p.ordinal
"""
_EXCERPT = "'MaxWords=28, MinWords=12, MaxFragments=2, FragmentDelimiter=\" … \", StartSel=«, StopSel=»'"
# A document number as a number, so 9 comes before 10 (numbers are text: some carry letters).
_NUMBER = "nullif(regexp_replace(d.number, '\\D', '', 'g'), '')::numeric"
# A document's current texts that have provisions (alias t), the text a reading starts from first.
_READABLE = """
SELECT t.id, t.sha256, t.language, t.origin, t.method, t.structure_problems, {main} AS main,
       coalesce(c.storage_key, b.storage_key) AS storage_key, c.id IS NOT NULL AS corrected
FROM registry.text_version t JOIN registry.blob b ON b.sha256 = t.sha256 {correction}
WHERE t.document_id = %s AND t.is_current
  AND EXISTS (SELECT 1 FROM registry.provision p WHERE p.text_version_id = t.id)
ORDER BY t.id
"""
# What other documents changed in each provision of a text (alias p), and where the new wording is: the changing
# document's own provision quoting the article (pasal-i/pasal-115 for pasal-115).
_CHANGES = f"""
SELECT l.to_address, l.type, l.from_document, changing.citation, {TAKES_EFFECT},
       (SELECT q.address FROM registry.provision q
        JOIN registry.text_version v ON v.id = q.text_version_id AND v.is_current
        WHERE l.type = 'amends' AND q.document_id = l.from_document AND q.address LIKE '%%/' || l.to_address
        ORDER BY v.id, q.ordinal LIMIT 1)
FROM registry.link l {TAKING_EFFECT}
WHERE l.to_document = %s AND l.to_address IS NOT NULL AND l.type IN ('amends', 'partly_revokes', 'revokes')
ORDER BY 5 NULLS LAST, l.from_document, l.type
"""
# Held documents, filtered by one check (or none); those whose last good version is still published first.
_HELD_ROWS = """
SELECT h.document_id, d.title, h.reasons, p.published_at, h.held_since
FROM registry.hold h JOIN registry.document d ON d.id = h.document_id
LEFT JOIN published.document p ON p.id = h.document_id
WHERE %(check)s::text IS NULL OR h.reasons @> jsonb_build_array(jsonb_build_object('check', %(check)s::text))
"""

# Published documents with gaps left to review, each with its notes in the text's reading order.
_GAP_ROWS = """
SELECT r.document_id, d.title, array_agg(ARRAY[r.address, r.note] ORDER BY r.ordinal)
FROM published.review r JOIN published.document d ON d.id = r.document_id
GROUP BY r.document_id, d.title ORDER BY r.document_id LIMIT %s OFFSET %s
"""


def _paged(page: int, total: int) -> tuple[int, int]:
    """The page asked for, kept within the pages `total` rows fill; and how many there are (one, when empty)."""
    pages = max(1, -(-total // PAGE_SIZE))
    return min(max(page, 1), pages), pages


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
            (gaps,) = self.connection.execute("SELECT count(DISTINCT document_id) FROM published.review").fetchone()
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
            gaps=gaps,
        )

    def held_page(self, check: str | None, page: int) -> HeldPage:
        by_check = dict(
            self.connection.execute(
                "SELECT reason ->> 'check', count(DISTINCT h.document_id) "
                "FROM registry.hold h, jsonb_array_elements(h.reasons) reason GROUP BY 1"
            ).fetchall()
        )
        (total,) = self.connection.execute(f"SELECT count(*) FROM ({_HELD_ROWS}) held", {"check": check}).fetchone()
        page, pages = _paged(page, total)
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

    def gap_page(self, page: int) -> GapPage:
        (total,) = self.connection.execute("SELECT count(DISTINCT document_id) FROM published.review").fetchone()
        page, pages = _paged(page, total)
        rows = self.connection.execute(_GAP_ROWS, (PAGE_SIZE, (page - 1) * PAGE_SIZE))
        return GapPage(
            rows=tuple(
                GapRow(document_id, title, tuple(ReviewNote(address, note) for address, note in notes))
                for document_id, title, notes in rows
            ),
            total=total,
            page=page,
            pages=pages,
        )

    def review_page(self, kind: str, page: int) -> ReviewPage:
        (total,) = self.connection.execute(
            "SELECT count(*) FROM curation.review_item WHERE kind = %s AND state = 'open'", (kind,)
        ).fetchone()
        page, pages = _paged(page, total)
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
                "SELECT q.problems, q.source_id, b.connector FROM ingest.quarantine q "
                "JOIN ingest.bundle b ON b.id = q.bundle_id WHERE q.bundle_id = %s AND q.line = %s",
                (subject.get("bundle_id"), subject.get("line")),
            ).fetchone()
            if row is None:
                return f"Bundle {subject.get('bundle_id')}, line {subject.get('line')}: the line is no longer in the " \
                       "quarantine"
            problems, source_id, connector = row
            named = f", {source_id}" if source_id else ""
            return f"Bundle {subject.get('bundle_id')} ({connector}), line {subject.get('line')}{named}: " \
                   f"{'; '.join(problems[:PROBLEMS_SHOWN])}"
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

    def search(self, query: str, filters: SearchFilters, kind: str, page: int) -> SearchPage:
        terms = {"q": query, "p": "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"}
        matching = self.connection.execute(_ARTICLE_HITS, terms).fetchall() if query else []
        by_metadata = _BY_METADATA if query else "true"
        hits = {
            row[0]: DocumentHit(*row)
            for row in self.connection.execute(
                _HITS + f", LATERAL (SELECT {by_metadata} AS by_metadata) m "
                "WHERE m.by_metadata OR d.id = ANY(%(worded)s) "
                f"ORDER BY lower(d.id) = lower(%(q)s) DESC, m.by_metadata DESC, d.year DESC NULLS LAST, d.issuer, "
                f"d.family, {_NUMBER} DESC NULLS LAST, d.id",
                {**terms, "worded": list({row[0] for row in matching})},
            )
        }
        kept = {hit.id: hit for hit in hits.values() if _passes(hit, filters)}
        articles = [row for row in matching if row[0] in kept]
        offset = (page - 1) * SEARCH_PAGE_SIZE
        shown = articles[offset : offset + SEARCH_PAGE_SIZE] if kind == "articles" else []
        total = len(kept) if kind == "documents" else len(articles)
        return SearchPage(
            query=query,
            kind=kind,
            filters=filters,
            documents=tuple(list(kept.values())[offset : offset + SEARCH_PAGE_SIZE]) if kind == "documents" else (),
            articles=self._excerpts(query, shown, kept),
            documents_total=len(kept),
            articles_total=len(articles),
            facets=tuple(_facet(name, hits.values(), filters) for name in FACETS),
            page=page,
            pages=max(1, -(-total // SEARCH_PAGE_SIZE)),
        )

    def _excerpts(self, query: str, shown: list, documents: dict[str, DocumentHit]) -> tuple[ArticleHit, ...]:
        """The articles shown, each with its matching words in context."""
        if not shown:
            return ()
        found = {
            (document, sha, address): (label, heading, " ".join(excerpt.split()))
            for document, sha, address, label, heading, excerpt in self.connection.execute(
                "SELECT p.document_id, p.text_sha256, p.address, p.label, p.heading, "
                f"ts_headline('simple', p.body, websearch_to_tsquery('simple', %(q)s), {_EXCERPT}) "
                "FROM published.provision p "
                "WHERE (p.document_id, p.text_sha256, p.address) IN "
                "(SELECT * FROM unnest(%(d)s::text[], %(s)s::text[], %(a)s::text[]))",
                {"q": query, "d": [r[0] for r in shown], "s": [r[1] for r in shown], "a": [r[2] for r in shown]},
            )
        }
        hits = []
        for document, sha, address, _ in shown:
            label, heading, excerpt = found[(document, sha, address)]
            hit = documents[document]
            hits.append(ArticleHit(document, hit.citation, hit.title, address, label, heading, excerpt, hit.status))
        return tuple(hits)

    def series(self) -> tuple[SeriesRow, ...]:
        rows = self.connection.execute(
            "SELECT issuer, family, count(*), min(year), max(year) FROM registry.document "
            "WHERE id NOT LIKE 'unresolved:%%' GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2"
        )
        return tuple(SeriesRow(*row) for row in rows)

    def series_page(self, issuer: str, family: str, year: int | None) -> SeriesPage | None:
        years = tuple(
            (held_year, count)
            for held_year, count in self.connection.execute(
                "SELECT year, count(*) FROM registry.document WHERE issuer = %s AND family = %s "
                "AND id NOT LIKE 'unresolved:%%' AND year IS NOT NULL GROUP BY 1 ORDER BY 1 DESC",
                (issuer, family),
            )
        )
        if not years:
            return None
        shown = year if year is not None else years[0][0]
        documents = tuple(
            DocumentHit(*row)
            for row in self.connection.execute(
                _HITS + "WHERE d.issuer = %s AND d.family = %s AND d.year = %s AND d.id NOT LIKE 'unresolved:%%' "
                f"ORDER BY {_NUMBER} NULLS LAST, d.number, d.id",
                (issuer, family, shown),
            )
        )
        return SeriesPage(issuer, family, years, shown, documents)

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
                    "SELECT e.address, e.status, e.effective_from, e.source, l.from_document, d.citation "
                    "FROM registry.status_event e LEFT JOIN registry.link l ON l.id = e.link_id "
                    "LEFT JOIN registry.document d ON d.id = l.from_document WHERE e.document_id = %s "
                    "ORDER BY e.effective_from NULLS FIRST, e.recorded_at",
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

    def reading_source(self, document_id: str, sha256: str | None) -> ReadingSource | None:
        summary = self.connection.execute(
            "SELECT citation, title FROM registry.document WHERE id = %s", (document_id,)
        ).fetchone()
        if summary is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            readable = cursor.execute(
                _READABLE.format(main=MAIN_TEXT, correction=_CORRECTION), (document_id,)
            ).fetchall()
        chosen = next((t for t in readable if sha256 in (None, t["sha256"])), None)
        if chosen is None:
            return None
        changes: dict[str, list[ProvisionChange]] = {}
        for address, *change in self.connection.execute(_CHANGES, (document_id,)):
            changes.setdefault(address, []).append(ProvisionChange(*change))
        provisions = tuple(
            SourceProvision(*row, changes=tuple(changes.get(row[0], ())))
            for row in self.connection.execute(
                "SELECT address, parent_address, kind, label, heading, char_start, char_end, page_start, page_end, "
                "valid_to FROM registry.provision WHERE text_version_id = %s ORDER BY ordinal",
                (chosen["id"],),
            )
        )
        pdf = self.connection.execute(
            "SELECT f.sha256 FROM registry.document_file f JOIN registry.blob b USING (sha256) "
            "WHERE f.document_id = %s AND f.role = 'main' AND b.media_type = 'application/pdf' "
            "ORDER BY f.sha256 LIMIT 1",
            (document_id,),
        ).fetchone()
        return ReadingSource(
            document_id=document_id,
            citation=summary[0],
            title=summary[1],
            sha256=chosen["sha256"],
            storage_key=chosen["storage_key"],
            problems=tuple(chosen["structure_problems"] or ()),
            corrected=chosen["corrected"],
            editable=chosen["main"],
            pdf_sha256=pdf[0] if pdf else None,
            texts=tuple(
                ReadableText(t["sha256"], t["language"], _detail(t["origin"], t["method"]), t["main"]) for t in readable
            ),
            provisions=provisions,
        )

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
                _detail(origin, method),
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
            f"SELECT l.type, l.{there}, d.title, l.from_address, l.to_address, l.method, d.citation, "
            f"coalesce(l.effective_on, {TAKES_EFFECT}) FROM registry.link l {TAKING_EFFECT} "
            f"LEFT JOIN registry.document d ON d.id = l.{there} "
            f"WHERE l.{here} = %s ORDER BY l.type, l.{there}, l.to_address NULLS FIRST",
            (document_id,),
        )
        return tuple(LinkRow(*row) for row in rows)

    def _open_reviews(self, document_id: str) -> tuple[ReviewRow, ...]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                _REVIEW_ROWS + " WHERE r.state = 'open' AND d.id = %s ORDER BY r.created_at", (document_id,)
            ).fetchall()
        return tuple(self._review_row(row) for row in rows)


def _passes(hit: DocumentHit, filters: SearchFilters, *, but: str | None = None) -> bool:
    return all(
        getattr(filters, name) is None or getattr(hit, name) == getattr(filters, name) for name in FACETS if name != but
    )


def _facet(name: str, hits, filters: SearchFilters) -> Facet:
    """Each value of a facet, counted over the matches the other filters leave: choosing one shows its count."""
    counts: dict[str, int] = {}
    for hit in hits:
        value = getattr(hit, name)
        if value is not None and _passes(hit, filters, but=name):
            counts[str(value)] = counts.get(str(value), 0) + 1
    order = (lambda item: (-int(item[0]),)) if name == "year" else (lambda item: (-item[1], item[0]))
    return Facet(name, tuple(sorted(counts.items(), key=order)))


def _detail(origin: str, method: str) -> str:
    """How a text was made, in words: "self extracted, text layer"."""
    return f"{origin.replace('_', ' ')}, {method.replace('_', ' ')}"


def _hold_reasons(stored: list[dict]) -> tuple[HoldReason, ...]:
    return tuple(HoldReason(Check(reason["check"]), reason["detail"]) for reason in stored)


def _at(received: dict, path: str) -> Any:
    value: Any = received
    for key in path.strip("{}").split(","):
        value = value.get(key) if isinstance(value, dict) else None
    return value
