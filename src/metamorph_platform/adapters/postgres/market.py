"""PostgreSQL side of the market data layer: market (records as received) and published_market (the read contract).

The connection runs in autocommit mode; every operation that must be atomic opens its own transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import astuple

import psycopg
from metamorph_market import LicensedEntityRecord, from_dict, to_dict
from psycopg.types.json import Jsonb

from metamorph_platform.application.ports import StoredBlob
from metamorph_platform.domain.loading import SaveOutcome
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo


class PostgresMarket:
    """The market store (loading) and the market source (publishing)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def registers(self) -> set[str]:
        return {register for (register,) in self.connection.execute("SELECT id FROM market.register")}

    def package_hash(self, connector: str, source_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT package_hash FROM market.entity WHERE connector = %s AND source_id = %s", (connector, source_id)
        ).fetchone()
        return row[0] if row else None

    def seen_again(self, connector: str, source_id: str, bundle_id: int) -> None:
        self.connection.execute(
            "UPDATE market.entity SET last_seen_at = now(), bundle_id = %s, missing_since = NULL "
            "WHERE connector = %s AND source_id = %s",
            (bundle_id, connector, source_id),
        )

    def save(
        self, record: LicensedEntityRecord, *, bundle_id: int, package_hash: str, files: Mapping[str, StoredBlob]
    ) -> SaveOutcome:
        """Keyed by the entity's ID, the license key: a number printed another way updates the same row."""
        entity, source = record.entity, record.source
        with self.connection.transaction():
            for blob in files.values():
                self.connection.execute(
                    "INSERT INTO market.file (sha256, media_type, storage_key, size_bytes) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (sha256) DO NOTHING",
                    (blob.sha256, blob.media_type, blob.storage_key, blob.size_bytes),
                )
            existed = self.connection.execute(
                "SELECT 1 FROM market.entity WHERE id = %s FOR UPDATE", (entity.id,)
            ).fetchone()
            self.connection.execute(
                """
                INSERT INTO market.entity (id, register, connector, source_id, package_hash, record, bundle_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET register = EXCLUDED.register, connector = EXCLUDED.connector,
                    source_id = EXCLUDED.source_id, package_hash = EXCLUDED.package_hash, record = EXCLUDED.record,
                    bundle_id = EXCLUDED.bundle_id, last_seen_at = now(), missing_since = NULL
                """,
                (entity.id, entity.register, source.connector, source.source_id, package_hash,
                 Jsonb(to_dict(record)), bundle_id),
            )
        return SaveOutcome.CHANGED if existed else SaveOutcome.NEW

    def mark_missing(self, connector: str, present: set[str]) -> int:
        gone = self.connection.execute(
            "UPDATE market.entity SET missing_since = now() "
            "WHERE connector = %s AND missing_since IS NULL AND NOT (source_id = ANY(%s)) RETURNING id",
            (connector, list(present)),
        ).fetchall()
        return len(gone)

    def register_infos(self) -> list[RegisterInfo]:
        rows = self.connection.execute("SELECT id, issuer, name, governed_by FROM market.register ORDER BY id")
        return [RegisterInfo(id_, issuer, name, tuple(governed_by)) for id_, issuer, name, governed_by in rows]

    def current_records(self) -> list[LicensedEntityRecord]:
        rows = self.connection.execute("SELECT record FROM market.entity WHERE missing_since IS NULL ORDER BY id")
        return [from_dict(record) for (record,) in rows]

    def storage_keys(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT sha256, storage_key FROM market.file").fetchall())


class PostgresPublishedMarket:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def replace_all(self, publication: MarketPublication) -> None:
        """One transaction: deleting the registers cascades to everything published under them."""
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM published_market.register")
            cursor.executemany(
                "INSERT INTO published_market.register (id, issuer, name, governed_by, newest_edition, editions) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [_row(register) for register in publication.registers],
            )
            cursor.executemany(
                'INSERT INTO published_market.edition (register, edition, listed, joined, "left", sha256, source_url, '
                "storage_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [_row(edition) for edition in publication.editions],
            )
            cursor.executemany(
                "INSERT INTO published_market.company (id, register, legal_name, names, business_type, status, "
                "first_listed, left_after) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [_row(company) for company in publication.companies],
            )
            cursor.executemany(
                "INSERT INTO published_market.entity (id, company_id, register, kind, license_number, license_date, "
                "legal_name, names, business_type, website, channels, first_listed, last_listed, on_newest_list, "
                "left_after, review_notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [_row(entity) for entity in publication.entities],
            )
            cursor.executemany(
                "INSERT INTO published_market.listing (entity_id, edition, legal_name, page, row_number, cells) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(*_row(listing)[:-1], Jsonb(dict(listing.cells))) for listing in publication.listings],
            )


def _row(published: object) -> tuple[object, ...]:
    """A published row's values in column order; tuples become lists, which psycopg sends as arrays."""
    return tuple(list(value) if isinstance(value, tuple) else value for value in astuple(published))
