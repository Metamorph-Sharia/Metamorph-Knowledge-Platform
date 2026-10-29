"""PostgreSQL side of the console's market pages: published_market as the read contract, and the curated links.

A market bundle is told from a regulation one by its manifest: the market contract's lists `records`, contract v2's
`documents`. The market's health checks are its connectors', its registers' and its statistics sources'.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from metamorph_platform.application.market_views import (
    PAGE_SIZE,
    CompanyFilters,
    CompanyPage,
    CompanyRow,
    CompanyView,
    DatasetFilters,
    DatasetPage,
    DatasetRow,
    DatasetView,
    EntityRow,
    IndustryName,
    IndustryView,
    MarketCounts,
    MarketOverview,
    MarketSeriesRow,
    MarketSources,
    MentionRow,
    NamedTarget,
    ObservationRow,
    PassageRow,
    RegisterView,
    ReleasePage,
    ReleaseRow,
    ReleaseView,
    ReportRow,
    ReportView,
    SectorView,
    SeriesView,
    StatisticsSourceView,
    pages,
)
from metamorph_platform.application.views import BundleRow, CheckRow

MARKET_BUNDLE = "b.manifest ? 'records'"
RECENT_BUNDLES = 8
COMPANY = "c.id, c.register, c.legal_name, c.status, c.business_type, c.first_listed, c.left_after"
DATASET = ('d.id, d.source, d.industry, d."group", d.metric, d.register, d.series, d.first_period, d.last_period, '
           "d.updated")
SERIES = "s.id, s.label, s.frequency, s.unit, s.first_period, s.last_period, s.observations"
REPORT = "r.id, r.issuer, r.family, r.edition, r.title, r.published_on, r.pages, r.passages, r.method"
RELEASE = "r.id, r.number, r.title, r.published_on, r.passages"


class PostgresMarketViews:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def overview(self) -> MarketOverview:
        health = self._one("SELECT taken_at, checks FROM ingest.health_snapshot ORDER BY taken_at DESC LIMIT 1")
        market_checks = self._market_check_names()
        counts = self._one(
            "SELECT (SELECT count(*) FROM published_market.company) AS companies, "
            "(SELECT count(*) FROM published_market.entity) AS entities, "
            "(SELECT count(*) FROM published_market.dataset) AS datasets, "
            "(SELECT count(*) FROM published_market.series) AS series, "
            "(SELECT coalesce(sum(observations), 0) FROM published_market.series) AS observations, "
            "(SELECT count(*) FROM published_market.report) AS reports, "
            "(SELECT count(*) FROM published_market.release) AS releases, "
            "(SELECT count(*) FROM published_market.mention) AS mentions, "
            "(SELECT count(*) FROM published_market.sector) AS sectors"
        )
        (open_reviews,) = self.connection.execute(
            "SELECT count(*) FROM curation.review_item i "
            "JOIN ingest.bundle b ON b.id = (i.subject->>'bundle_id')::bigint "
            f"WHERE i.state = 'open' AND {MARKET_BUNDLE}"
        ).fetchone()
        bundles = self._all(
            "SELECT connector, run_id, state, received_at, loaded, unchanged, quarantined FROM ingest.bundle b "
            f"WHERE {MARKET_BUNDLE} ORDER BY received_at DESC LIMIT %s", (RECENT_BUNDLES,)
        )
        checks = [CheckRow(**check) for check in health["checks"] if check["name"] in market_checks] if health else []
        return MarketOverview(
            checks=tuple(checks),
            health_taken_at=health["taken_at"] if health else None,
            counts=MarketCounts(**{key: int(value) for key, value in counts.items()}),
            open_reviews=open_reviews,
            recent_bundles=tuple(BundleRow(**row) for row in bundles),
        )

    def sources(self) -> MarketSources:
        registers = self._all(
            "SELECT m.id, m.issuer, m.name, m.governed_by, m.reports, m.fresh_days, p.newest_edition, "
            "coalesce(p.editions, 0) AS editions, "
            "(SELECT count(*) FROM published_market.company c WHERE c.register = m.id) AS companies "
            "FROM market.register m LEFT JOIN published_market.register p ON p.id = m.id ORDER BY m.id"
        )
        sources = self._all(
            "SELECT m.id, m.issuer, m.name, m.citation, m.fresh_days, m.download_page, m.download_hint, "
            "count(d.id) AS datasets, coalesce(sum(d.series), 0) AS series, max(d.last_period) AS newest_period "
            "FROM market.statistics_source m LEFT JOIN published_market.dataset d ON d.source = m.id "
            "GROUP BY m.id ORDER BY m.id"
        )
        industries = self._all(
            "SELECT m.source, m.name, m.register, m.governed_by, m.reports, "
            "coalesce(cardinality(p.datasets), 0) AS datasets FROM market.industry m "
            "LEFT JOIN published_market.industry p ON p.source = m.source AND p.name = m.name ORDER BY 1, 2"
        )
        sectors = self._all(
            "SELECT s.id, s.name, s.name_en, coalesce(p.registers, '{}') AS registers, "
            "coalesce(p.governed_by, '{}') AS governed_by, coalesce(p.reports, '{}') AS reports, "
            "coalesce(cardinality(p.datasets), 0) AS datasets, "
            "coalesce((SELECT array_agg(ARRAY[i.source, i.name] ORDER BY i.ordinal) FROM market.sector_industry i "
            "WHERE i.sector = s.id), '{}') AS industries "
            "FROM market.sector s LEFT JOIN published_market.sector p ON p.id = s.id ORDER BY s.id"
        )
        named = self.connection.execute(
            "SELECT DISTINCT source, industry FROM published_market.dataset WHERE industry IS NOT NULL ORDER BY 1, 2"
        ).fetchall()
        return MarketSources(
            registers=tuple(RegisterView(**_tuples(row)) for row in registers),
            sources=tuple(StatisticsSourceView(**{**row, "series": int(row["series"])}) for row in sources),
            industries=tuple(IndustryView(**_tuples(row)) for row in industries),
            sectors=tuple(
                SectorView(**_tuples({**row, "industries": tuple(IndustryName(*pair) for pair in row["industries"])}))
                for row in sectors
            ),
            named_industries=tuple(IndustryName(source, industry) for source, industry in named),
        )

    def companies(self, query: str, filters: CompanyFilters, page: int) -> CompanyPage:
        where, params = ["true"], []
        if query:
            where.append("(c.legal_name ILIKE %s OR EXISTS (SELECT 1 FROM unnest(c.names) n WHERE n ILIKE %s))")
            params += [f"%{query}%"] * 2
        for column, value in (("register", filters.register), ("status", filters.status),
                              ("business_type", filters.business_type)):
            if value:
                where.append(f"c.{column} = %s")
                params.append(value)
        condition = " AND ".join(where)
        (total,) = self.connection.execute(
            f"SELECT count(*) FROM published_market.company c WHERE {condition}", params
        ).fetchone()
        rows = self._all(
            f"SELECT {COMPANY} FROM published_market.company c WHERE {condition} ORDER BY c.legal_name, c.id "
            "LIMIT %s OFFSET %s", (*params, PAGE_SIZE, _offset(page))
        )
        return CompanyPage(tuple(CompanyRow(**row) for row in rows), total, page, pages(total))

    def company(self, company_id: str) -> CompanyView | None:
        found = self._one(f"SELECT {COMPANY}, c.names FROM published_market.company c WHERE c.id = %s", (company_id,))
        if found is None:
            return None
        names = found.pop("names")
        entities = self._all(
            "SELECT id, kind, license_number, license_date, legal_name, business_type, website, first_listed, "
            "last_listed, on_newest_list, left_after, review_notes FROM published_market.entity WHERE company_id = %s "
            "ORDER BY license_date NULLS LAST, id", (company_id,)
        )
        return CompanyView(
            company=CompanyRow(**found),
            names=tuple(names),
            entities=tuple(EntityRow(**_tuples(row)) for row in entities),
            mentions=self._mentions("company", company_id),
        )

    def datasets(self, query: str, filters: DatasetFilters, page: int) -> DatasetPage:
        where, params = ["true"], []
        if query:
            where.append('(d.id ILIKE %s OR d.metric ILIKE %s OR d."group" ILIKE %s)')
            params += [f"%{query}%"] * 3
        for column, value in (("source", filters.source), ("industry", filters.industry)):
            if value:
                where.append(f"d.{column} = %s")
                params.append(value)
        condition = " AND ".join(where)
        (total,) = self.connection.execute(
            f"SELECT count(*) FROM published_market.dataset d WHERE {condition}", params
        ).fetchone()
        rows = self._all(
            f"SELECT {DATASET} FROM published_market.dataset d WHERE {condition} ORDER BY d.source, d.id "
            "LIMIT %s OFFSET %s", (*params, PAGE_SIZE, _offset(page))
        )
        return DatasetPage(tuple(DatasetRow(**row) for row in rows), total, page, pages(total))

    def dataset(self, dataset_id: str, page: int) -> DatasetView | None:
        found = self._one(
            f"SELECT {DATASET}, d.governed_by, d.reports, d.citation, d.url FROM published_market.dataset d "
            "WHERE d.id = %s", (dataset_id,)
        )
        if found is None:
            return None
        extra = {key: found.pop(key) for key in ("governed_by", "reports", "citation", "url")}
        series = self._all(
            f"SELECT {SERIES} FROM published_market.series s WHERE s.dataset = %s ORDER BY s.id LIMIT %s OFFSET %s",
            (dataset_id, PAGE_SIZE, _offset(page)),
        )
        return DatasetView(
            dataset=DatasetRow(**found),
            governed_by=tuple(extra["governed_by"]),
            reports=tuple(extra["reports"]),
            citation=extra["citation"],
            url=extra["url"],
            series=tuple(MarketSeriesRow(**row) for row in series),
            series_total=found["series"],
            page=page,
            pages=pages(found["series"]),
        )

    def series(self, series_id: str) -> SeriesView | None:
        found = self._one(
            f"SELECT {SERIES}, s.dataset, s.measure, s.dimensions, d.citation, d.url FROM published_market.series s "
            "JOIN published_market.dataset d ON d.id = s.dataset WHERE s.id = %s", (series_id,)
        )
        if found is None:
            return None
        extra = {key: found.pop(key) for key in ("dataset", "measure", "dimensions", "citation", "url")}
        observations = self.connection.execute(
            "SELECT period, value, provisional FROM published_market.observation WHERE series_id = %s ORDER BY period",
            (series_id,),
        ).fetchall()
        return SeriesView(
            series=MarketSeriesRow(**found),
            dataset=extra["dataset"],
            measure=extra["measure"],
            dimensions=tuple(extra["dimensions"]),
            citation=extra["citation"],
            url=extra["url"],
            observations=tuple(ObservationRow(*row) for row in observations),
        )

    def reports(self) -> tuple[ReportRow, ...]:
        rows = self._all(
            f"SELECT {REPORT} FROM published_market.report r ORDER BY r.published_on DESC NULLS LAST, r.id"
        )
        return tuple(ReportRow(**row) for row in rows)

    def report(self, report_id: str, page: int) -> ReportView | None:
        found = self._one(f"SELECT {REPORT}, r.citation, r.url FROM published_market.report r WHERE r.id = %s",
                          (report_id,))
        if found is None:
            return None
        citation, url = found.pop("citation"), found.pop("url")
        passages = self._passages(
            "SELECT address, ordinal, page_start, page_end, text, words FROM published_market.report_passage "
            "WHERE report = %s ORDER BY ordinal LIMIT %s OFFSET %s", (report_id, PAGE_SIZE, _offset(page)),
            "report", report_id,
        )
        return ReportView(ReportRow(**found), citation, url, passages, page, pages(found["passages"]))

    def releases(self, query: str, published_from: date | None, published_to: date | None, page: int) -> ReleasePage:
        where, params = ["true"], []
        if query:
            where.append("(r.title ILIKE %s OR r.number ILIKE %s)")
            params += [f"%{query}%"] * 2
        if published_from:
            where.append("r.published_on >= %s")
            params.append(published_from)
        if published_to:
            where.append("r.published_on <= %s")
            params.append(published_to)
        condition = " AND ".join(where)
        (total,) = self.connection.execute(
            f"SELECT count(*) FROM published_market.release r WHERE {condition}", params
        ).fetchone()
        rows = self._all(
            f"SELECT {RELEASE} FROM published_market.release r WHERE {condition} ORDER BY r.published_on DESC, r.id "
            "LIMIT %s OFFSET %s", (*params, PAGE_SIZE, _offset(page))
        )
        return ReleasePage(tuple(ReleaseRow(**row) for row in rows), total, page, pages(total))

    def release(self, release_id: str) -> ReleaseView | None:
        found = self._one(f"SELECT {RELEASE}, r.citation, r.url FROM published_market.release r WHERE r.id = %s",
                          (release_id,))
        if found is None:
            return None
        citation, url = found.pop("citation"), found.pop("url")
        passages = self._passages(
            "SELECT address, ordinal, NULL::integer AS page_start, NULL::integer AS page_end, text, words "
            "FROM published_market.release_passage WHERE release = %s ORDER BY ordinal", (release_id,),
            "release", release_id,
        )
        return ReleaseView(ReleaseRow(**found), citation, url, passages)

    # --- shared ----------------------------------------------------------------------------------------------

    def _market_check_names(self) -> set[str]:
        rows = self.connection.execute(
            f"SELECT DISTINCT connector FROM ingest.bundle b WHERE {MARKET_BUNDLE} "
            "UNION SELECT 'register ' || id FROM market.register "
            "UNION SELECT 'statistics ' || id FROM market.statistics_source"
        )
        return {name for (name,) in rows}

    def _mentions(self, target_kind: str, target: str) -> tuple[MentionRow, ...]:
        rows = self._all(
            "SELECT m.kind, m.document, m.address, coalesce(r.citation, p.citation) AS citation, "
            "coalesce(r.title, p.title) AS title, coalesce(r.published_on, p.published_on) AS published_on "
            "FROM published_market.mention m "
            "LEFT JOIN published_market.release r ON m.kind = 'release' AND r.id = m.document "
            "LEFT JOIN published_market.report p ON m.kind = 'report' AND p.id = m.document "
            "WHERE m.target_kind = %s AND m.target = %s ORDER BY published_on DESC NULLS LAST, m.document, m.address",
            (target_kind, target),
        )
        return tuple(MentionRow(**row) for row in rows)

    def _passages(self, query: str, params: tuple, kind: str, document: str) -> tuple[PassageRow, ...]:
        rows = self._all(query, params)
        named: dict[str, list[NamedTarget]] = {}
        for address, target_kind, target in self.connection.execute(
            "SELECT address, target_kind, target FROM published_market.mention WHERE kind = %s AND document = %s "
            "ORDER BY address, target_kind DESC, target", (kind, document)
        ):
            named.setdefault(address, []).append(NamedTarget(target_kind, target))
        return tuple(PassageRow(**row, names=tuple(named.get(row["address"], ()))) for row in rows)

    def _one(self, query: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(query, params).fetchone()

    def _all(self, query: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(query, params).fetchall()


def _tuples(row: dict[str, Any]) -> dict[str, Any]:
    """PostgreSQL arrays arrive as lists; the read models hold tuples."""
    return {key: tuple(value) if isinstance(value, list) else value for key, value in row.items()}


def _offset(page: int) -> int:
    return (max(page, 1) - 1) * PAGE_SIZE
