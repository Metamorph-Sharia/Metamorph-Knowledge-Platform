"""What the console's market pages show: read models over published_market and the curated links, and their port.

Queries, not use cases: no rule decides anything here. Each model is plain, immutable data, so the API renders it
without knowing where it came from. Lists are paged (PAGE_SIZE); a dataset's series and a report's passages too, since
BPS's largest table holds about 10,000 series.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from metamorph_platform.application.views import BundleRow, CheckRow

PAGE_SIZE = 50
COMPANY_STATUSES = ("licensed", "registered", "left")
BUSINESS_TYPES = ("sharia", "conventional")


@dataclass(frozen=True)
class MarketCounts:
    companies: int
    entities: int  # licences and registrations
    datasets: int
    series: int
    observations: int
    reports: int
    releases: int
    mentions: int
    sectors: int


@dataclass(frozen=True)
class MarketOverview:
    checks: tuple[CheckRow, ...]  # the market's checks in the newest health snapshot
    health_taken_at: datetime | None
    counts: MarketCounts
    open_reviews: int  # open review items of market bundles: quarantined lines
    recent_bundles: tuple[BundleRow, ...]


@dataclass(frozen=True)
class IndustryName:
    source: str
    name: str  # as the source names it


@dataclass(frozen=True)
class RegisterView:
    id: str
    issuer: str
    name: str
    governed_by: tuple[str, ...]  # curated
    reports: tuple[str, ...]  # curated: IDs or families
    fresh_days: int
    newest_edition: date | None
    editions: int
    companies: int


@dataclass(frozen=True)
class StatisticsSourceView:
    id: str
    issuer: str
    name: str
    citation: str | None
    fresh_days: int
    download_page: str | None  # where a curator downloads an edition by hand (SEKI)
    download_hint: str | None
    datasets: int
    series: int
    newest_period: date | None  # the first day of the newest period published


@dataclass(frozen=True)
class IndustryView:
    source: str
    name: str
    register: str | None
    governed_by: tuple[str, ...]  # its own; a register's are on the register
    reports: tuple[str, ...]
    datasets: int


@dataclass(frozen=True)
class SectorView:
    id: str
    name: str
    name_en: str
    industries: tuple[IndustryName, ...]
    registers: tuple[str, ...]  # as published: what its industries link
    governed_by: tuple[str, ...]
    reports: tuple[str, ...]
    datasets: int


@dataclass(frozen=True)
class MarketSources:
    """Everything a curator keeps on the market's sources page: the curated links, and what they reach."""

    registers: tuple[RegisterView, ...]
    sources: tuple[StatisticsSourceView, ...]
    industries: tuple[IndustryView, ...]
    sectors: tuple[SectorView, ...]
    named_industries: tuple[IndustryName, ...]  # every industry the published datasets name, linked or not


@dataclass(frozen=True)
class CompanyRow:
    id: str
    register: str
    legal_name: str
    status: str  # licensed, registered or left
    business_type: str | None  # sharia or conventional
    first_listed: date | None
    left_after: date | None


@dataclass(frozen=True)
class CompanyPage:
    rows: tuple[CompanyRow, ...]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class EntityRow:
    id: str
    kind: str  # license or registration
    license_number: str
    license_date: date | None
    legal_name: str
    business_type: str | None
    website: str | None
    first_listed: date | None
    last_listed: date | None
    on_newest_list: bool
    left_after: date | None
    review_notes: tuple[str, ...]


@dataclass(frozen=True)
class MentionRow:
    """A report or release passage that names a regulation or a company."""

    kind: str  # report or release
    document: str
    address: str
    citation: str
    title: str
    published_on: date | None


@dataclass(frozen=True)
class CompanyView:
    company: CompanyRow
    names: tuple[str, ...]
    entities: tuple[EntityRow, ...]
    mentions: tuple[MentionRow, ...]  # newest first


@dataclass(frozen=True)
class DatasetRow:
    id: str
    source: str
    industry: str | None
    group: str
    metric: str
    register: str | None
    series: int
    first_period: date
    last_period: date
    updated: date | None


@dataclass(frozen=True)
class DatasetPage:
    rows: tuple[DatasetRow, ...]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class MarketSeriesRow:
    id: str
    label: str
    frequency: str
    unit: str | None
    first_period: date
    last_period: date
    observations: int


@dataclass(frozen=True)
class DatasetView:
    dataset: DatasetRow
    governed_by: tuple[str, ...]
    reports: tuple[str, ...]
    citation: str | None
    url: str | None
    series: tuple[MarketSeriesRow, ...]  # a page of them
    series_total: int
    page: int
    pages: int


@dataclass(frozen=True)
class ObservationRow:
    period: date  # the period's first day
    value: float
    provisional: bool


@dataclass(frozen=True)
class SeriesView:
    series: MarketSeriesRow
    dataset: str
    measure: str
    dimensions: tuple[Mapping[str, str], ...]
    citation: str | None
    url: str | None
    observations: tuple[ObservationRow, ...]  # oldest first


@dataclass(frozen=True)
class ReportRow:
    id: str
    issuer: str
    family: str
    edition: str
    title: str
    published_on: date | None
    pages: int
    passages: int
    method: str  # text_layer or ocr


@dataclass(frozen=True)
class NamedTarget:
    kind: str  # regulation or company
    id: str


@dataclass(frozen=True)
class PassageRow:
    address: str
    ordinal: int
    page_start: int | None  # a release has no pages
    page_end: int | None
    text: str
    words: int
    names: tuple[NamedTarget, ...]  # what the passage names


@dataclass(frozen=True)
class ReportView:
    report: ReportRow
    citation: str
    url: str | None
    passages: tuple[PassageRow, ...]  # a page of them
    page: int
    pages: int


@dataclass(frozen=True)
class ReleaseRow:
    id: str
    number: str | None
    title: str
    published_on: date
    passages: int


@dataclass(frozen=True)
class ReleasePage:
    rows: tuple[ReleaseRow, ...]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class ReleaseView:
    release: ReleaseRow
    citation: str
    url: str | None
    passages: tuple[PassageRow, ...]


@dataclass(frozen=True)
class CompanyFilters:
    register: str | None = None
    status: str | None = None
    business_type: str | None = None


@dataclass(frozen=True)
class DatasetFilters:
    source: str | None = None
    industry: str | None = None


class MarketViews(Protocol):
    def overview(self) -> MarketOverview: ...

    def sources(self) -> MarketSources: ...

    def companies(self, query: str, filters: CompanyFilters, page: int) -> CompanyPage:
        """`query` matches a legal name or another name, in part, ignoring case; empty lists them all."""
        ...

    def company(self, company_id: str) -> CompanyView | None: ...

    def datasets(self, query: str, filters: DatasetFilters, page: int) -> DatasetPage:
        """`query` matches a dataset's ID, metric or group, in part, ignoring case; empty lists them all."""
        ...

    def dataset(self, dataset_id: str, page: int) -> DatasetView | None: ...

    def series(self, series_id: str) -> SeriesView | None: ...

    def reports(self) -> tuple[ReportRow, ...]: ...

    def report(self, report_id: str, page: int) -> ReportView | None: ...

    def releases(self, query: str, published_from: date | None, published_to: date | None, page: int) -> ReleasePage:
        """`query` matches a title or a number, in part, ignoring case; newest first."""
        ...

    def release(self, release_id: str) -> ReleaseView | None: ...


def pages(total: int) -> int:
    return max(1, -(-total // PAGE_SIZE))
