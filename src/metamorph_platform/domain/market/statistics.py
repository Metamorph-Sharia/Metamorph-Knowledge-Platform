"""published_market's statistics, built from the series records: plain rows, so publishing stays a pure function.

A dataset is one of the source's tables (a portal cube, a SEKI table, a BPS table). It is linked to the regulation
layer through its industry, a curated link (market.industry): a register, whose regulations it then shares, or
regulations of its own. An industry without a link, and a macro dataset without an industry, are published unlinked.
A period is published as its first day (2026-Q2 → 2026-04-01), beside its series' frequency.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from metamorph_market import SeriesRecord


@dataclass(frozen=True)
class IndustryLink:
    """An industry as a statistics source names it, curated in market.industry."""

    source: str  # e.g. "ojk:portal"
    industry: str  # as the source names it, e.g. "Bank Umum Syariah"
    register: str | None  # the register of its licensed entities, e.g. "ojk:lpbbti"
    governed_by: tuple[str, ...]  # its regulations, when it has no register
    reports: tuple[str, ...] = ()  # its reports: IDs, or families (ojk:lpksi) for every edition


@dataclass(frozen=True)
class PublishedDataset:
    id: str
    source: str
    industry: str | None  # None for a macro dataset
    group: str
    metric: str
    register: str | None
    governed_by: tuple[str, ...]
    series: int
    first_period: date
    last_period: date
    updated: date | None  # when the source last updated the data, as its newest answer says
    url: str | None
    citation: str | None  # how its source asks to be cited, from market.statistics_source
    reports: tuple[str, ...] = ()  # the published reports its industry's curated links name


@dataclass(frozen=True)
class PublishedSeries:
    id: str
    dataset: str
    measure: str
    label: str  # the measure and its members' labels, e.g. "Posisi Keuangan: 003. 1. Kas dan Setara Kas"
    dimensions: tuple[Mapping[str, str], ...]  # name, key, label
    first_period: date
    last_period: date
    observations: int
    frequency: str  # monthly, quarterly, semiannual or annual
    unit: str | None  # as the source states it


@dataclass(frozen=True)
class PublishedObservation:
    series_id: str
    period: date  # the period's first day
    value: float
    storage_key: str | None  # the answer it was read from, in the object store
    provisional: bool  # the source marks the period provisional


@dataclass(frozen=True)
class Statistics:
    datasets: tuple[PublishedDataset, ...]
    series: tuple[PublishedSeries, ...]
    observations: tuple[PublishedObservation, ...]


def source_of(dataset: str) -> str:
    """"ojk:portal:bu_syariah_posisikeuangan" → "ojk:portal": the issuer and source a dataset ID starts with."""
    return ":".join(dataset.split(":")[:2])


def statistics(
    links: Sequence[IndustryLink],
    registers: Mapping[str, tuple[str, ...]],
    records: Sequence[SeriesRecord],
    storage_keys: Mapping[str, str],
    citations: Mapping[str, str] | None = None,
) -> Statistics:
    """`registers`: each register's regulations; `storage_keys`: where each answer (by sha256) is kept;
    `citations`: how each source asks to be cited."""
    linked = {(link.source, link.industry): link for link in links}
    by_dataset: dict[str, list[SeriesRecord]] = {}
    for record in records:
        by_dataset.setdefault(record.series.dataset, []).append(record)
    return Statistics(
        datasets=tuple(_dataset(members, linked, registers, citations or {}) for members in by_dataset.values()),
        series=tuple(_series(record) for record in records),
        observations=tuple(
            PublishedObservation(record.series.id, period_start(observation.period), observation.value,
                                 storage_keys.get(observation.file), observation.provisional)
            for record in records
            for observation in record.observations
        ),
    )


def _dataset(
    records: list[SeriesRecord],
    linked: Mapping[tuple[str, str], IndustryLink],
    registers: Mapping[str, tuple[str, ...]],
    citations: Mapping[str, str],
) -> PublishedDataset:
    series = records[0].series
    source = source_of(series.dataset)
    link = linked.get((source, series.industry)) if series.industry else None
    register = link.register if link else None
    governed_by = registers.get(register, ()) if register else (link.governed_by if link else ())
    periods = [observation.period for record in records for observation in record.observations]
    editions = [file.edition for record in records for file in record.files]
    return PublishedDataset(
        id=series.dataset,
        source=source,
        industry=series.industry,
        group=series.group,
        metric=series.metric,
        register=register,
        governed_by=governed_by,
        series=len(records),
        first_period=min(period_start(period) for period in periods),
        last_period=max(period_start(period) for period in periods),
        updated=date.fromisoformat(max(editions)) if editions else None,
        url=records[0].source.url,
        citation=citations.get(source),
    )


def _series(record: SeriesRecord) -> PublishedSeries:
    series, periods = record.series, [observation.period for observation in record.observations]
    labels = " / ".join(dimension.label for dimension in series.dimensions)
    return PublishedSeries(
        id=series.id,
        dataset=series.dataset,
        measure=series.measure,
        label=f"{series.measure}: {labels}" if labels else series.measure,
        dimensions=tuple({"name": d.name, "key": d.key, "label": d.label} for d in series.dimensions),
        first_period=period_start(min(periods)),
        last_period=period_start(max(periods)),
        observations=len(periods),
        frequency=str(series.frequency),
        unit=series.unit,
    )


def period_start(period: str) -> date:
    """2026-08 → 2026-08-01; 2026-Q2 → 2026-04-01; 2026-S2 → 2026-07-01; 2025 → 2025-01-01."""
    year, _, within = period.partition("-")
    if not within:
        return date(int(year), 1, 1)
    if within[0] == "Q":
        return date(int(year), 3 * int(within[1:]) - 2, 1)
    if within[0] == "S":
        return date(int(year), 6 * int(within[1:]) - 5, 1)
    return date(int(year), int(within), 1)
