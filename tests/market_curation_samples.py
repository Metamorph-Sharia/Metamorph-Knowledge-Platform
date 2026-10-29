"""In-memory stand-ins for curating the market layer and reading its pages: the use case's ports, and MarketViews."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from metamorph_platform.application.market_views import (
    CompanyFilters,
    CompanyPage,
    CompanyRow,
    CompanyView,
    DatasetFilters,
    DatasetPage,
    DatasetRow,
    DatasetView,
    MarketCounts,
    MarketOverview,
    MarketSources,
    ReleasePage,
    ReleaseRow,
    ReleaseView,
    ReportRow,
    ReportView,
    SeriesView,
    StatisticsSourceView,
)
from metamorph_platform.application.ports import Curator
from metamorph_platform.domain.market.curation import RegisterLinks, SourceSettings
from metamorph_platform.domain.market.links import SectorDefinition
from metamorph_platform.domain.market.statistics import IndustryLink

ANI = Curator("ani", "Ani Rahma")
BUS = "Bank Umum Syariah"
COMPANY = CompanyRow("ojk:lpbbti:kep-88-d.05-2021", "ojk:lpbbti", "PT Fintech Bina Bangsa", "licensed", "sharia",
                     date(2021, 1, 31), None)
DATASET = DatasetRow("ojk:portal:bu_syariah_posisikeuangan", "ojk:portal", BUS, "Posisi Keuangan", "Posisi Keuangan",
                     None, 2, date(2026, 1, 1), date(2026, 2, 1), date(2026, 10, 26))
RELEASE = ReleaseRow("ojk:siaran-pers:2026:x", "SP 188/DKPU/OJK/X/2026", "Siaran Pers: X", date(2026, 10, 8), 1)


class MemoryMarketCuration:
    """Records each change, and whether it happened inside one atomic change with the relink."""

    def __init__(self, journal: list[str]) -> None:
        self.journal = journal

    @contextmanager
    def atomically(self):  # noqa: ANN201
        self.journal.append("begin")
        yield
        self.journal.append("commit")

    def set_register_links(self, curator: Curator, register_id: str, links: RegisterLinks, reason: str) -> None:
        self.journal.append(f"register {register_id} {links.governed_by} by {curator.username}: {reason}")

    def set_industry(self, curator: Curator, link: IndustryLink, reason: str) -> None:
        self.journal.append(f"industry {link.source} {link.industry} {link.register}: {reason}")

    def withdraw_industry(self, curator: Curator, source: str, name: str, reason: str) -> None:
        self.journal.append(f"withdraw industry {source} {name}: {reason}")

    def set_source(self, curator: Curator, source_id: str, settings: SourceSettings, reason: str) -> None:
        self.journal.append(f"source {source_id} {settings.download_page}: {reason}")

    def set_sector(self, curator: Curator, sector: SectorDefinition, reason: str) -> None:
        self.journal.append(f"sector {sector.id} {len(sector.industries)}: {reason}")

    def withdraw_sector(self, curator: Curator, sector_id: str, reason: str) -> None:
        self.journal.append(f"withdraw sector {sector_id}: {reason}")


class MemoryPublishedNames:
    def documents(self, ids: list[str]) -> set[str]:
        return {id_ for id_ in ids if id_ == "ojk:pojk:2024:40"}

    def reports(self) -> list[str]:
        return ["ojk:lpksi:2025"]


class JournalledRelink:
    def __init__(self, journal: list[str]) -> None:
        self.journal = journal

    def run(self) -> None:
        self.journal.append("relink")


class MemoryMarketViews:
    """Answers each page with one row, and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple] = []

    def overview(self) -> MarketOverview:
        return MarketOverview((), None, MarketCounts(2, 3, 1, 2, 3, 1, 1, 2, 0), 1, ())

    def sources(self) -> MarketSources:
        seki = StatisticsSourceView("bi:seki", "bi", "SEKI", "Bank Indonesia, SEKI", 90, "https://www.bi.go.id/seki",
                                    "SEKI_{MONTH}_{YEAR}.zip", 107, 6919, date(2026, 9, 1))
        return MarketSources((), (seki,), (), (), ())

    def companies(self, query: str, filters: CompanyFilters, page: int) -> CompanyPage:
        self.asked.append(("companies", query, filters, page))
        return CompanyPage((COMPANY,), 1, page, 1)

    def company(self, company_id: str) -> CompanyView | None:
        return CompanyView(COMPANY, (), (), ()) if company_id == COMPANY.id else None

    def datasets(self, query: str, filters: DatasetFilters, page: int) -> DatasetPage:
        self.asked.append(("datasets", query, filters, page))
        return DatasetPage((DATASET,), 1, page, 1)

    def dataset(self, dataset_id: str, page: int) -> DatasetView | None:
        return DatasetView(DATASET, (), (), None, None, (), 2, page, 1) if dataset_id == DATASET.id else None

    def series(self, series_id: str) -> SeriesView | None:
        return None

    def reports(self) -> tuple[ReportRow, ...]:
        return ()

    def report(self, report_id: str, page: int) -> ReportView | None:
        return None

    def releases(self, query: str, published_from: date | None, published_to: date | None, page: int) -> ReleasePage:
        self.asked.append(("releases", query, published_from, published_to, page))
        return ReleasePage((RELEASE,), 1, page, 1)

    def release(self, release_id: str) -> ReleaseView | None:
        return ReleaseView(RELEASE, "Siaran Pers OJK SP 188", None, ()) if release_id == RELEASE.id else None
