"""PostgreSQL side of curating the market layer's links: the change and its audit row, in one transaction.

The links live in the market schema (market.register, industry, statistics_source, sector): reference data no
connector writes, so nothing a later load does can undo a change. Who changed what, and why, is in curation.audit_log.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from metamorph_platform.adapters.postgres.curation import audit, learn_curator
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.domain.market.curation import RegisterLinks, SourceSettings
from metamorph_platform.domain.market.links import SectorDefinition
from metamorph_platform.domain.market.statistics import IndustryLink


class PostgresMarketCuration:
    """The market curation actions, and what is published, for their warnings."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    @contextmanager
    def atomically(self) -> Iterator[None]:
        with self.connection.transaction():
            yield

    def set_register_links(self, curator: Curator, register_id: str, links: RegisterLinks, reason: str) -> None:
        with self.connection.transaction():
            before = self._row("SELECT governed_by, reports, fresh_days FROM market.register WHERE id = %s FOR UPDATE",
                               (register_id,), missing=f"no register {register_id}")
            self.connection.execute(
                "UPDATE market.register SET governed_by = %s, reports = %s, fresh_days = %s WHERE id = %s",
                (list(links.governed_by), list(links.reports), links.fresh_days, register_id),
            )
            after = {"governed_by": list(links.governed_by), "reports": list(links.reports),
                     "fresh_days": links.fresh_days}
            self._audit(curator, "market.set_register_links", {"register": register_id}, before, after, reason)

    def set_industry(self, curator: Curator, link: IndustryLink, reason: str) -> None:
        with self.connection.transaction():
            self._require_source(link.source)
            if link.register:
                self._row("SELECT 1 FROM market.register WHERE id = %s", (link.register,),
                          missing=f"no register {link.register}")
            before = self._found(
                "SELECT register, governed_by, reports FROM market.industry WHERE source = %s AND name = %s FOR UPDATE",
                (link.source, link.industry),
            )
            after = {"register": link.register, "governed_by": list(link.governed_by), "reports": list(link.reports)}
            self.connection.execute(
                "INSERT INTO market.industry (source, name, register, governed_by, reports) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (source, name) DO UPDATE SET register = EXCLUDED.register, "
                "governed_by = EXCLUDED.governed_by, reports = EXCLUDED.reports",
                (link.source, link.industry, *after.values()),
            )
            target = {"source": link.source, "name": link.industry}
            self._audit(curator, "market.set_industry", target, before, after, reason)

    def withdraw_industry(self, curator: Curator, source: str, name: str, reason: str) -> None:
        with self.connection.transaction():
            before = self._row(
                "DELETE FROM market.industry WHERE source = %s AND name = %s RETURNING register, governed_by, reports",
                (source, name), missing=f"no industry {name} of {source}",
            )
            self._audit(curator, "market.withdraw_industry", {"source": source, "name": name}, before, None, reason)

    def set_source(self, curator: Curator, source_id: str, settings: SourceSettings, reason: str) -> None:
        with self.connection.transaction():
            before = self._row(
                "SELECT citation, fresh_days, download_page, download_hint FROM market.statistics_source "
                "WHERE id = %s FOR UPDATE",
                (source_id,), missing=f"no statistics source {source_id}",
            )
            after = {"citation": settings.citation, "fresh_days": settings.fresh_days,
                     "download_page": settings.download_page, "download_hint": settings.download_hint}
            self.connection.execute(
                "UPDATE market.statistics_source SET citation = %s, fresh_days = %s, download_page = %s, "
                "download_hint = %s WHERE id = %s",
                (*after.values(), source_id),
            )
            self._audit(curator, "market.set_source", {"source": source_id}, before, after, reason)

    def set_sector(self, curator: Curator, sector: SectorDefinition, reason: str) -> None:
        with self.connection.transaction():
            for source in dict.fromkeys(source for source, _ in sector.industries):
                self._require_source(source)
            before = self._sector(sector.id)
            self.connection.execute(
                "INSERT INTO market.sector (id, name, name_en) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, name_en = EXCLUDED.name_en",
                (sector.id, sector.name, sector.name_en),
            )
            self.connection.execute("DELETE FROM market.sector_industry WHERE sector = %s", (sector.id,))
            with self.connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO market.sector_industry (sector, source, name, ordinal) VALUES (%s, %s, %s, %s)",
                    [(sector.id, source, name, ordinal) for ordinal, (source, name) in enumerate(sector.industries)],
                )
            after = {"name": sector.name, "name_en": sector.name_en,
                     "industries": [[source, name] for source, name in sector.industries]}
            self._audit(curator, "market.set_sector", {"sector": sector.id}, before, after, reason)

    def withdraw_sector(self, curator: Curator, sector_id: str, reason: str) -> None:
        with self.connection.transaction():
            before = self._sector(sector_id)
            if before is None:
                raise CurationRefused(f"no sector {sector_id}")
            self.connection.execute("DELETE FROM market.sector WHERE id = %s", (sector_id,))  # cascades to industries
            self._audit(curator, "market.withdraw_sector", {"sector": sector_id}, before, None, reason)

    # --- what is published, for the warnings -------------------------------------------------------------------

    def documents(self, ids: list[str]) -> set[str]:
        rows = self.connection.execute("SELECT id FROM published.document WHERE id = ANY(%s)", (ids,))
        return {id_ for (id_,) in rows}

    def reports(self) -> list[str]:
        return [id_ for (id_,) in self.connection.execute("SELECT id FROM published_market.report ORDER BY id")]

    # --- shared ----------------------------------------------------------------------------------------------

    def _sector(self, sector_id: str) -> dict[str, Any] | None:
        return self._found(
            "SELECT s.name, s.name_en, coalesce(array_agg(ARRAY[i.source, i.name] ORDER BY i.ordinal) "
            "FILTER (WHERE i.source IS NOT NULL), '{}') AS industries "
            "FROM market.sector s LEFT JOIN market.sector_industry i ON i.sector = s.id WHERE s.id = %s GROUP BY s.id",
            (sector_id,),
        )

    def _require_source(self, source: str) -> None:
        self._row("SELECT 1 FROM market.statistics_source WHERE id = %s", (source,),
                  missing=f"no statistics source {source}")

    def _row(self, query: str, params: tuple, *, missing: str) -> dict[str, Any]:
        found = self._found(query, params)
        if found is None:
            raise CurationRefused(missing)
        return found

    def _found(self, query: str, params: tuple) -> dict[str, Any] | None:
        cursor = self.connection.execute(query, params)
        row = cursor.fetchone()
        return None if row is None else {column.name: value for column, value in zip(cursor.description, row,
                                                                                     strict=True)}

    def _audit(self, curator: Curator, action: str, target: dict, before: Any, after: Any, reason: str) -> None:
        learn_curator(self.connection, curator)
        audit(self.connection, curator, action, target, before, after, reason)
