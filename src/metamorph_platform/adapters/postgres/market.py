"""PostgreSQL side of the market data layer: market (records as received) and published_market (the read contract).

Licensed entities are kept in market.entity, series in market.series and reports in market.report; a connector
sends one kind.

The connection runs in autocommit mode; every operation that must be atomic opens its own transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import astuple

import psycopg
from metamorph_market import LicensedEntityRecord, MarketRecord, ReportRecord, SeriesRecord, from_dict, to_dict
from psycopg.types.json import Jsonb

from metamorph_platform.application.ports import StoredBlob
from metamorph_platform.domain.loading import SaveOutcome
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo
from metamorph_platform.domain.market.statistics import IndustryLink, source_of

RECORD_TABLES = ("market.entity", "market.series", "market.report")  # fixed names, never input


class PostgresMarket:
    """The market store (loading) and the market source (publishing)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def registers(self) -> set[str]:
        return {register for (register,) in self.connection.execute("SELECT id FROM market.register")}

    def sources(self) -> set[str]:
        return {source for (source,) in self.connection.execute("SELECT id FROM market.statistics_source")}

    def package_hash(self, connector: str, source_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT package_hash FROM market.entity WHERE connector = %s AND source_id = %s "
            "UNION ALL SELECT package_hash FROM market.series WHERE connector = %s AND source_id = %s "
            "UNION ALL SELECT package_hash FROM market.report WHERE connector = %s AND source_id = %s",
            (connector, source_id) * 3,
        ).fetchone()
        return row[0] if row else None

    def seen_again(self, connector: str, source_id: str, bundle_id: int) -> None:
        for table in RECORD_TABLES:
            self.connection.execute(
                f"UPDATE {table} SET last_seen_at = now(), bundle_id = %s, missing_since = NULL "
                "WHERE connector = %s AND source_id = %s",
                (bundle_id, connector, source_id),
            )

    def save(
        self, record: MarketRecord, *, bundle_id: int, package_hash: str, files: Mapping[str, StoredBlob]
    ) -> SaveOutcome:
        """Keyed by the record's ID (a license key, a series' key): a number printed another way updates the row."""
        with self.connection.transaction():
            for blob in files.values():
                self.connection.execute(
                    "INSERT INTO market.file (sha256, media_type, storage_key, size_bytes) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (sha256) DO NOTHING",
                    (blob.sha256, blob.media_type, blob.storage_key, blob.size_bytes),
                )
            if isinstance(record, SeriesRecord):
                return self._upsert("market.series", "source", record.series.id,
                                    source_of(record.series.dataset), record, bundle_id, package_hash)
            if isinstance(record, ReportRecord):
                return self._upsert("market.report", "issuer", record.report.id, record.report.issuer, record,
                                    bundle_id, package_hash)
            return self._upsert("market.entity", "register", record.entity.id, record.entity.register, record,
                                bundle_id, package_hash)

    def _upsert(
        self, table: str, scope: str, id_: str, scope_id: str, record: MarketRecord, bundle_id: int, package_hash: str
    ) -> SaveOutcome:
        existed = self.connection.execute(f"SELECT 1 FROM {table} WHERE id = %s FOR UPDATE", (id_,)).fetchone()
        self.connection.execute(
            f"""
            INSERT INTO {table} (id, {scope}, connector, source_id, package_hash, record, bundle_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET {scope} = EXCLUDED.{scope}, connector = EXCLUDED.connector,
                source_id = EXCLUDED.source_id, package_hash = EXCLUDED.package_hash, record = EXCLUDED.record,
                bundle_id = EXCLUDED.bundle_id, last_seen_at = now(), missing_since = NULL
            """,
            (id_, scope_id, record.source.connector, record.source.source_id, package_hash,
             Jsonb(to_dict(record)), bundle_id),
        )
        return SaveOutcome.CHANGED if existed else SaveOutcome.NEW

    def mark_missing(self, connector: str, present: set[str], within: set[str] | None = None) -> int:
        if within is not None:  # whole datasets: only their series can go missing
            return len(self.connection.execute(
                "UPDATE market.series SET missing_since = now() WHERE connector = %s AND missing_since IS NULL "
                "AND NOT (source_id = ANY(%s)) AND record->'series'->>'dataset' = ANY(%s) RETURNING id",
                (connector, list(present), list(within)),
            ).fetchall())
        gone = 0
        for table in RECORD_TABLES:
            gone += len(self.connection.execute(
                f"UPDATE {table} SET missing_since = now() "
                "WHERE connector = %s AND missing_since IS NULL AND NOT (source_id = ANY(%s)) RETURNING id",
                (connector, list(present)),
            ).fetchall())
        return gone

    def register_infos(self) -> list[RegisterInfo]:
        rows = self.connection.execute("SELECT id, issuer, name, governed_by, reports FROM market.register ORDER BY id")
        return [RegisterInfo(id_, issuer, name, tuple(governed_by), tuple(reports))
                for id_, issuer, name, governed_by, reports in rows]

    def industry_links(self) -> list[IndustryLink]:
        rows = self.connection.execute(
            "SELECT source, name, register, governed_by, reports FROM market.industry ORDER BY 1, 2"
        )
        return [IndustryLink(*link[:3], tuple(link[3]), tuple(link[4])) for link in rows]

    def current_records(self) -> list[LicensedEntityRecord]:
        rows = self.connection.execute("SELECT record FROM market.entity WHERE missing_since IS NULL ORDER BY id")
        return [from_dict(record) for (record,) in rows]

    def current_series(self) -> list[SeriesRecord]:
        rows = self.connection.execute("SELECT record FROM market.series WHERE missing_since IS NULL ORDER BY id")
        return [from_dict(record) for (record,) in rows]

    def current_reports(self) -> list[ReportRecord]:
        rows = self.connection.execute("SELECT record FROM market.report WHERE missing_since IS NULL ORDER BY id")
        return [from_dict(record) for (record,) in rows]

    def storage_keys(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT sha256, storage_key FROM market.file").fetchall())

    def citations(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT id, citation FROM market.statistics_source WHERE citation IS NOT NULL")
        return dict(rows.fetchall())


class PostgresPublishedMarket:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def replace_all(self, publication: MarketPublication) -> None:
        """One transaction: deleting the registers, datasets and reports cascades to everything published under them."""
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM published_market.register")
            cursor.execute("DELETE FROM published_market.dataset")
            cursor.execute("DELETE FROM published_market.report")
            cursor.execute("DELETE FROM published_market.industry")
            cursor.executemany(
                "INSERT INTO published_market.register (id, issuer, name, governed_by, newest_edition, editions, "
                "reports) VALUES (%s, %s, %s, %s, %s, %s, %s)",
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
            self._replace_statistics(cursor, publication)
            cursor.executemany(
                "INSERT INTO published_market.report (id, issuer, family, edition, title, published_on, language, url, "
                "citation, pages, passages, method, storage_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s)",
                [_row(report) for report in publication.reports.reports],
            )
            cursor.executemany(
                "INSERT INTO published_market.report_passage (report, address, ordinal, page_start, page_end, text, "
                "words) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [_row(passage) for passage in publication.reports.passages],
            )
            cursor.executemany(
                "INSERT INTO published_market.industry (source, name, register, governed_by, reports, datasets) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [_row(industry) for industry in publication.industries],
            )

    @staticmethod
    def _replace_statistics(cursor: psycopg.Cursor, publication: MarketPublication) -> None:
        found = publication.statistics
        cursor.executemany(
            'INSERT INTO published_market.dataset (id, source, industry, "group", metric, register, governed_by, '
            "series, first_period, last_period, updated, url, citation, reports) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [_row(dataset) for dataset in found.datasets],
        )
        cursor.executemany(
            "INSERT INTO published_market.series (id, dataset, measure, label, dimensions, first_period, last_period, "
            "observations, frequency, unit) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(series.id, series.dataset, series.measure, series.label, Jsonb([dict(d) for d in series.dimensions]),
              series.first_period, series.last_period, series.observations, series.frequency, series.unit)
             for series in found.series],
        )
        with cursor.copy(
            "COPY published_market.observation (series_id, period, value, storage_key, provisional) FROM STDIN"
        ) as copy:
            for observation in found.observations:
                copy.write_row(astuple(observation))


def _row(published: object) -> tuple[object, ...]:
    """A published row's values in column order; tuples become lists, which psycopg sends as arrays."""
    return tuple(list(value) if isinstance(value, tuple) else value for value in astuple(published))
