"""PostgreSQL side of publishing: snapshots read from registry + curation, rows written to `published`."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from metamorph_platform.domain.publishing import (
    DocumentSnapshot,
    LinkRecord,
    Override,
    ProvisionRecord,
    PublishedDocument,
    SourceRecord,
    StatusEventRecord,
    StoredContent,
)

DOCUMENT_COLUMNS = (
    "issuer",
    "family",
    "number",
    "year",
    "citation",
    "title",
    "language",
    "kind",
    "id_confidence",
    "status",
    "status_as_of",
    "enacted_on",
    "promulgated_on",
    "effective_on",
)

_TO_PUBLISH = """
SELECT d.id FROM registry.document d LEFT JOIN published.document p ON p.id = d.id
WHERE %(everything)s
   OR p.id IS NULL
   OR d.updated_at > p.published_at
   OR EXISTS (SELECT 1 FROM curation.override o WHERE o.document_id = d.id AND o.created_at > p.published_at)
   OR EXISTS (SELECT 1 FROM curation.suppression s WHERE s.document_id = d.id AND s.created_at > p.published_at)
UNION
SELECT p.id FROM published.document p WHERE NOT EXISTS (SELECT 1 FROM registry.document d WHERE d.id = p.id)
ORDER BY 1
"""


_DOCUMENT = f"SELECT {', '.join(DOCUMENT_COLUMNS)} FROM registry.document WHERE id = %s"
# One query per part of a snapshot, all read in the document's transaction.
_PARTS = {
    "aliases": "SELECT text FROM registry.alias WHERE document_id = %s ORDER BY text",
    "sources": (
        "SELECT connector, source_id, url, fetched_at, missing_since FROM registry.document_source "
        "WHERE document_id = %s ORDER BY connector, source_id"
    ),
    "files": (
        "SELECT f.sha256, f.rights, b.storage_key, f.role, b.media_type, f.title, f.source_url, f.pages "
        "FROM registry.document_file f JOIN registry.blob b USING (sha256) WHERE f.document_id = %s ORDER BY f.sha256"
    ),
    "texts": (
        "SELECT t.sha256, t.rights, b.storage_key, t.language, t.origin, t.method, t.paged, t.of_file "
        "FROM registry.text_version t JOIN registry.blob b USING (sha256) "
        "WHERE t.document_id = %s AND t.is_current ORDER BY t.language, t.sha256"
    ),
    "overrides": "SELECT field, value FROM curation.override WHERE document_id = %s AND active ORDER BY created_at",
    "suppression": "SELECT 1 FROM curation.suppression WHERE document_id = %s",
    "provisions": (
        "SELECT t.sha256 AS text_sha256, p.address, p.kind, p.label, p.ordinal, p.char_start, p.char_end, "
        "p.parent_address, p.heading, p.page_start, p.page_end, p.valid_from, p.valid_to "
        "FROM registry.provision p JOIN registry.text_version t ON t.id = p.text_version_id "
        "WHERE p.document_id = %s AND t.is_current ORDER BY t.sha256, p.ordinal"
    ),
    "links": (
        "SELECT type, from_address, to_document, to_address, effective_on, confidence FROM registry.link "
        "WHERE from_document = %s ORDER BY id"
    ),
    "status_events": (
        "SELECT address, status, effective_from, source FROM registry.status_event WHERE document_id = %s "
        "ORDER BY effective_from NULLS FIRST, id"
    ),
    "stated_dates": (
        "SELECT min(stated_enacted_on) AS enacted_on, min(stated_promulgated_on) AS promulgated_on, "
        "min(stated_effective_on) AS effective_on FROM registry.text_version WHERE document_id = %s AND is_current"
    ),
}


class PostgresPublication:
    """Reads what to publish (PublicationSource) and writes it (PublishedStore)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # --- PublicationSource ------------------------------------------------------------

    def documents_to_publish(self, everything: bool = False) -> list[str]:
        return [row[0] for row in self.connection.execute(_TO_PUBLISH, {"everything": everything})]

    def snapshot(self, document_id: str) -> DocumentSnapshot | None:
        with self.connection.transaction(), self.connection.cursor(row_factory=dict_row) as cursor:
            values = cursor.execute(_DOCUMENT, (document_id,)).fetchone()
            if values is None:
                return None
            rows = {part: cursor.execute(sql, (document_id,)).fetchall() for part, sql in _PARTS.items()}
        return DocumentSnapshot(
            id=document_id,
            values=values,
            aliases=tuple(row["text"] for row in rows["aliases"]),
            sources=tuple(_source_record(row) for row in rows["sources"]),
            files=tuple(_stored_content(row) for row in rows["files"]),
            texts=tuple(_stored_content(row) for row in rows["texts"]),
            overrides=tuple(Override(row["field"], row["value"]) for row in rows["overrides"]),
            suppressed=bool(rows["suppression"]),
            provisions=tuple(ProvisionRecord(**row) for row in rows["provisions"]),
            links=tuple(LinkRecord(**row) for row in rows["links"]),
            status_events=tuple(StatusEventRecord(**row) for row in rows["status_events"]),
            stated_dates=rows["stated_dates"][0],
        )

    # --- PublishedStore -----------------------------------------------------------------

    def replace(self, document: PublishedDocument) -> bool:
        with self.connection.transaction():
            existed = self._delete(document.id)
            self._insert(document)
            self._log(document.id, "updated" if existed else "added")
        return not existed

    def remove(self, document_id: str) -> bool:
        with self.connection.transaction():
            existed = self._delete(document_id)
            if existed:
                self._log(document_id, "removed")
        return existed

    def _delete(self, document_id: str) -> bool:
        """Its sources, files, texts, provisions, links and status events go with it (ON DELETE CASCADE)."""
        return (
            self.connection.execute(
                "DELETE FROM published.document WHERE id = %s RETURNING id", (document_id,)
            ).fetchone()
            is not None
        )

    def _insert(self, document: PublishedDocument) -> None:
        values = {column: document.values.get(column) for column in DOCUMENT_COLUMNS}
        self.connection.execute(
            f"INSERT INTO published.document (id, {', '.join(DOCUMENT_COLUMNS)}, aliases, curated) "
            f"VALUES (%(id)s, {', '.join(f'%({c})s' for c in DOCUMENT_COLUMNS)}, %(aliases)s, %(curated)s)",
            {**values, "id": document.id, "aliases": list(document.aliases), "curated": document.curated},
        )
        for source in document.sources:
            self.connection.execute(
                "INSERT INTO published.document_source (document_id, connector, source_id, url, fetched_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (document.id, source.connector, source.source_id, source.url, source.fetched_at),
            )
        for file in document.files:
            self.connection.execute(
                "INSERT INTO published.file (document_id, sha256, role, media_type, title, source_url, pages, "
                "storage_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    document.id,
                    file.sha256,
                    file.details["role"],
                    file.details["media_type"],
                    file.details["title"],
                    file.details["source_url"],
                    file.details["pages"],
                    file.storage_key,
                ),
            )
        for text in document.texts:
            self.connection.execute(
                "INSERT INTO published.text (document_id, sha256, language, origin, method, paged, of_file, "
                "storage_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    document.id,
                    text.sha256,
                    text.details["language"],
                    text.details["origin"],
                    text.details["method"],
                    text.details["paged"],
                    text.details["of_file"],
                    text.storage_key,
                ),
            )
        self._insert_derived(document)

    def _insert_derived(self, document: PublishedDocument) -> None:
        with self.connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO published.provision (document_id, address, text_sha256, parent_address, kind, label, "
                "heading, ordinal, body, char_start, char_end, page_start, page_end, valid_from, valid_to) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (document.id, p.record.address, p.record.text_sha256, p.record.parent_address, p.record.kind,
                     p.record.label, p.record.heading, p.record.ordinal, p.body.replace("\x00", ""),
                     p.record.char_start, p.record.char_end, p.record.page_start, p.record.page_end,
                     p.record.valid_from, p.record.valid_to)
                    for p in document.provisions
                ],
            )  # fmt: skip
            cursor.executemany(
                "INSERT INTO published.link (type, from_document, from_address, to_document, to_address, "
                "effective_on, confidence) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(link.type, document.id, link.from_address, link.to_document, link.to_address, link.effective_on,
                  link.confidence) for link in document.links],
            )  # fmt: skip
            cursor.executemany(
                "INSERT INTO published.status_event (document_id, address, status, effective_from, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(document.id, e.address, e.status, e.effective_from, e.source) for e in document.status_events],
            )

    def _log(self, document_id: str, change: str) -> None:
        self.connection.execute(
            "INSERT INTO published.change_log (document_id, change) VALUES (%s, %s)", (document_id, change)
        )


def _source_record(row: dict) -> SourceRecord:
    missing_since = row["missing_since"]
    return SourceRecord(
        connector=row["connector"],
        source_id=row["source_id"],
        url=row["url"],
        fetched_at=row["fetched_at"].isoformat(),
        missing_since=missing_since.isoformat() if missing_since else None,
    )


def _stored_content(row: dict) -> StoredContent:
    details = dict(row)
    return StoredContent(
        sha256=details.pop("sha256"),
        rights=details.pop("rights"),
        storage_key=details.pop("storage_key"),
        details=details,
    )
