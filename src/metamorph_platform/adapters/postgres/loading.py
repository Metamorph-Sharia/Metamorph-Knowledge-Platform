"""PostgreSQL side of loading: the ingest ledger, the registry and the review queue.

The connection runs in autocommit mode; every operation that must be atomic opens its own transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import psycopg
from metamorph_contract import Manifest, NormalizedDocument, to_dict
from psycopg.types.json import Jsonb

from metamorph_platform.application.ports import BundleAlreadyLoaded, StoredBlob
from metamorph_platform.domain.aliases import aliases_of
from metamorph_platform.domain.loading import ReviewKind, SaveOutcome


class PostgresIngestLedger:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def start_bundle(self, manifest: Manifest, uri: str) -> int:
        """A failed run may be retried; a run that was received or loaded is refused."""
        with self.connection.transaction():
            row = self.connection.execute(
                "SELECT id, state FROM ingest.bundle WHERE connector = %s AND run_id = %s FOR UPDATE",
                (manifest.connector, manifest.run_id),
            ).fetchone()
            if row and row[1] != "failed":
                raise BundleAlreadyLoaded(f"{manifest.connector} run {manifest.run_id} is already {row[1]}")
            if row:
                self.connection.execute(
                    "UPDATE ingest.bundle SET state = 'received', received_at = now(), error = NULL, uri = %s "
                    "WHERE id = %s",
                    (uri, row[0]),
                )
                return row[0]
            (bundle_id,) = self.connection.execute(
                "INSERT INTO ingest.bundle (connector, connector_version, run_id, uri, manifest) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (manifest.connector, manifest.connector_version, manifest.run_id, uri, Jsonb(asdict(manifest))),
            ).fetchone()
            return bundle_id

    def quarantine(self, bundle_id: int, line: int, raw: str, problems: list[str], source_id: str | None) -> None:
        self.connection.execute(
            "INSERT INTO ingest.quarantine (bundle_id, line, source_id, problems, payload) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (bundle_id, line) DO UPDATE SET problems = EXCLUDED.problems, payload = EXCLUDED.payload",
            (bundle_id, line, source_id, Jsonb(problems), raw),
        )

    def finish_bundle(self, bundle_id: int, counts: Mapping[str, int]) -> None:
        self.connection.execute(
            "UPDATE ingest.bundle SET state = 'loaded', loaded_at = now(), loaded = %s, unchanged = %s, "
            "quarantined = %s, missing = %s WHERE id = %s",
            (
                counts["new"] + counts["changed"],
                counts["unchanged"],
                counts["quarantined"],
                counts["missing"],
                bundle_id,
            ),
        )

    def fail_bundle(self, bundle_id: int, error: str) -> None:
        self.connection.execute(
            "UPDATE ingest.bundle SET state = 'failed', error = %s WHERE id = %s", (error, bundle_id)
        )


class PostgresRegistry:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def package_hash(self, connector: str, source_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT package_hash FROM registry.document_source WHERE connector = %s AND source_id = %s",
            (connector, source_id),
        ).fetchone()
        return row[0] if row else None

    def seen_again(self, connector: str, source_id: str, bundle_id: int) -> None:
        with self.connection.transaction():
            row = self.connection.execute(
                "SELECT document_id, missing_since FROM registry.document_source "
                "WHERE connector = %s AND source_id = %s FOR UPDATE",
                (connector, source_id),
            ).fetchone()
            self.connection.execute(
                "UPDATE registry.document_source SET last_seen_at = now(), bundle_id = %s, missing_since = NULL "
                "WHERE connector = %s AND source_id = %s",
                (bundle_id, connector, source_id),
            )
            document_id, was_missing_since = row
            if was_missing_since is not None:
                _event(self.connection, "reappeared", connector, source_id, document_id)

    def assigned_id(self, connector: str, source_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT document_id FROM curation.id_assignment WHERE connector = %s AND source_id = %s",
            (connector, source_id),
        ).fetchone()
        return row[0] if row else None

    def save(
        self, document: NormalizedDocument, *, bundle_id: int, package_hash: str, blobs: Mapping[str, StoredBlob]
    ) -> SaveOutcome:
        source, info = document.source, document.document
        with self.connection.transaction():
            previous = self.connection.execute(
                "SELECT document_id FROM registry.document_source WHERE connector = %s AND source_id = %s FOR UPDATE",
                (source.connector, source.source_id),
            ).fetchone()
            old_status = self.connection.execute(
                "SELECT status FROM registry.document WHERE id = %s", (info.id,)
            ).fetchone()
            self._upsert_document(document)
            self._upsert_source(document, bundle_id, package_hash)
            self._store_blobs(blobs)
            self._replace_files(document)
            text_versions = self._upsert_texts(document)
            self._replace_provisions(document, text_versions)
            self._replace_citations(document)
            self._add_aliases(document)
            status = info.status.value.value
            if old_status is None or old_status[0] != status:
                self.connection.execute(
                    "INSERT INTO registry.status_event (document_id, status, source) VALUES (%s, %s, %s)",
                    (info.id, status, info.status.source),
                )
            self._record_save_event(source.connector, source.source_id, info.id, previous)
        return SaveOutcome.NEW if previous is None else SaveOutcome.CHANGED

    def mark_missing(self, connector: str, present: set[str]) -> int:
        with self.connection.transaction():
            gone = self.connection.execute(
                "UPDATE registry.document_source SET missing_since = now() "
                "WHERE connector = %s AND missing_since IS NULL AND NOT (source_id = ANY(%s)) "
                "RETURNING source_id, document_id",
                (connector, list(present)),
            ).fetchall()
            for source_id, document_id in gone:
                _event(self.connection, "missing_from_source", connector, source_id, document_id)
        return len(gone)

    # --- the parts of one save --------------------------------------------------------

    def _upsert_document(self, document: NormalizedDocument) -> None:
        info = document.document
        self.connection.execute(
            """
            INSERT INTO registry.document (id, issuer, family, number, year, citation, title, language, kind,
                id_confidence, status, status_source, status_as_of, enacted_on, promulgated_on, effective_on)
            VALUES (%(id)s, %(issuer)s, %(family)s, %(number)s, %(year)s, %(citation)s, %(title)s, %(language)s,
                %(kind)s, %(id_confidence)s, %(status)s, %(status_source)s, %(status_as_of)s, %(enacted)s,
                %(promulgated)s, %(effective)s)
            ON CONFLICT (id) DO UPDATE SET issuer = EXCLUDED.issuer, family = EXCLUDED.family,
                number = EXCLUDED.number, year = EXCLUDED.year, citation = EXCLUDED.citation, title = EXCLUDED.title,
                language = EXCLUDED.language, kind = EXCLUDED.kind, id_confidence = EXCLUDED.id_confidence,
                status = EXCLUDED.status, status_source = EXCLUDED.status_source, status_as_of = EXCLUDED.status_as_of,
                enacted_on = EXCLUDED.enacted_on, promulgated_on = EXCLUDED.promulgated_on,
                effective_on = EXCLUDED.effective_on, updated_at = now()
            """,
            {
                "id": info.id,
                "issuer": info.issuer,
                "family": info.family,
                "number": info.number,
                "year": info.year,
                "citation": info.citation,
                "title": info.title,
                "language": info.language,
                "kind": info.kind.value,
                "id_confidence": info.id_confidence.value,
                "status": info.status.value.value,
                "status_source": info.status.source,
                "status_as_of": info.status.as_of,
                "enacted": info.dates.enacted,
                "promulgated": info.dates.promulgated,
                "effective": info.dates.effective,
            },
        )

    def _upsert_source(self, document: NormalizedDocument, bundle_id: int, package_hash: str) -> None:
        source = document.source
        self.connection.execute(
            """
            INSERT INTO registry.document_source (connector, source_id, document_id, connector_version, url,
                fetched_at, received, source_fields, package_hash, bundle_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (connector, source_id) DO UPDATE SET document_id = EXCLUDED.document_id,
                connector_version = EXCLUDED.connector_version, url = EXCLUDED.url, fetched_at = EXCLUDED.fetched_at,
                received = EXCLUDED.received, source_fields = EXCLUDED.source_fields,
                package_hash = EXCLUDED.package_hash, bundle_id = EXCLUDED.bundle_id, last_seen_at = now(),
                missing_since = NULL
            """,
            (
                source.connector,
                source.source_id,
                document.document.id,
                source.connector_version,
                source.url,
                source.fetched_at,
                Jsonb(to_dict(document)),
                Jsonb(document.source_fields),
                package_hash,
                bundle_id,
            ),
        )

    def _store_blobs(self, blobs: Mapping[str, StoredBlob]) -> None:
        for blob in blobs.values():
            self.connection.execute(
                "INSERT INTO registry.blob (sha256, media_type, size_bytes, storage_key) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (sha256) DO NOTHING",
                (blob.sha256, blob.media_type, blob.size_bytes, blob.storage_key),
            )

    def _replace_files(self, document: NormalizedDocument) -> None:
        connector, document_id = document.source.connector, document.document.id
        self.connection.execute(
            "DELETE FROM registry.document_file WHERE document_id = %s AND connector = %s", (document_id, connector)
        )
        for file in document.files:
            self.connection.execute(
                "INSERT INTO registry.document_file (document_id, sha256, connector, role, title, source_url, rights, "
                "pages) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (document_id, sha256) DO NOTHING",
                (
                    document_id,
                    file.sha256,
                    connector,
                    file.role.value,
                    file.title,
                    file.source_url,
                    file.rights.value,
                    file.pages,
                ),
            )

    def _upsert_texts(self, document: NormalizedDocument) -> dict[str, int]:
        """Current texts by sha256 → text_version id. Earlier versions stay, marked not current."""
        connector, document_id = document.source.connector, document.document.id
        versions = {}
        for text in document.texts:
            (version_id,) = self.connection.execute(
                """
                INSERT INTO registry.text_version (document_id, sha256, of_file, connector, language, origin, method,
                    rights, paged)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, sha256) DO UPDATE SET is_current = true
                RETURNING id
                """,
                (
                    document_id,
                    text.sha256,
                    text.of_file,
                    connector,
                    text.language,
                    text.origin.value,
                    text.method.value,
                    text.rights.value,
                    text.paged,
                ),
            ).fetchone()
            versions[text.sha256] = version_id
        self.connection.execute(
            "UPDATE registry.text_version SET is_current = false "
            "WHERE document_id = %s AND connector = %s AND NOT (sha256 = ANY(%s))",
            (document_id, connector, list(versions)),
        )
        return versions

    def _replace_provisions(self, document: NormalizedDocument, versions: Mapping[str, int]) -> None:
        if not versions:
            return
        self.connection.execute(
            "DELETE FROM registry.provision WHERE origin = 'source' AND text_version_id = ANY(%s)",
            (list(versions.values()),),
        )
        for ordinal, provision in enumerate(document.provisions):
            self.connection.execute(
                """
                INSERT INTO registry.provision (text_version_id, address, document_id, parent_address, kind, label,
                    heading, ordinal, char_start, char_end, page_start, page_end, origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'source')
                """,
                (
                    versions[provision.text],
                    provision.address,
                    document.document.id,
                    provision.parent,
                    provision.kind,
                    provision.label,
                    provision.heading,
                    ordinal,
                    provision.char_start,
                    provision.char_end,
                    provision.page_start,
                    provision.page_end,
                ),
            )

    def _replace_citations(self, document: NormalizedDocument) -> None:
        source = document.source
        self.connection.execute(
            "DELETE FROM registry.citation WHERE connector = %s AND source_id = %s",
            (source.connector, source.source_id),
        )
        for citation in document.citations:
            self.connection.execute(
                """
                INSERT INTO registry.citation (document_id, connector, source_id, relation, target_text, target_id,
                    from_address, to_address, evidence, found_in, confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document.document.id,
                    source.connector,
                    source.source_id,
                    citation.relation.value,
                    citation.target_text,
                    citation.target_id,
                    citation.from_address,
                    citation.to_address,
                    citation.evidence,
                    citation.found_in.value,
                    citation.confidence.value,
                ),
            )

    def _add_aliases(self, document: NormalizedDocument) -> None:
        for key, text in aliases_of(document).items():
            self.connection.execute(
                "INSERT INTO registry.alias (alias_key, document_id, origin, text) VALUES (%s, %s, 'source', %s) "
                "ON CONFLICT (alias_key, document_id) DO NOTHING",
                (key, document.document.id, text),
            )

    def _record_save_event(self, connector: str, source_id: str, document_id: str, previous: tuple | None) -> None:
        if previous is None:
            _event(self.connection, "new_document", connector, source_id, document_id)
        elif previous[0] != document_id:
            _event(self.connection, "id_changed", connector, source_id, document_id, {"from": previous[0]})
        else:
            _event(self.connection, "document_changed", connector, source_id, document_id)


class PostgresReviewQueue:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def ensure_open(self, kind: ReviewKind, subject: Mapping[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO curation.review_item (kind, subject) SELECT %(kind)s, %(subject)s "
            "WHERE NOT EXISTS (SELECT 1 FROM curation.review_item "
            "WHERE kind = %(kind)s AND subject = %(subject)s AND state = 'open')",
            {"kind": kind.value, "subject": Jsonb(dict(subject))},
        )


def _event(
    connection: psycopg.Connection,
    kind: str,
    connector: str,
    source_id: str,
    document_id: str | None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO ingest.event (kind, connector, source_id, document_id, detail) VALUES (%s, %s, %s, %s, %s)",
        (kind, connector, source_id, document_id, Jsonb(dict(detail or {}))),
    )
