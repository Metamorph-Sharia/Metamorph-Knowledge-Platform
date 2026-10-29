"""Curated links between the market layer's parts, the law and the reports, resolved against what is published.

A register or an industry names its reports in market.register.reports and market.industry.reports, each a report
ID (ojk:roadmap:2023:rp3si) or a family (ojk:lpksi), which names every edition published: a new edition is linked
without curating it. A link to a report not published names nothing. A sector gathers industries across the sources'
own names (market.sector). Curated, never inferred.

A full publish (`with_links`) and a links-only one (`relinked`, after a curator changes a link) resolve links with the
same functions, so the two never disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from metamorph_platform.domain.market.statistics import IndustryLink, PublishedDataset, industry_regulations

if TYPE_CHECKING:
    from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo


def linked_reports(references: Sequence[str], published: Sequence[str]) -> tuple[str, ...]:
    """The published reports the references name: each family's editions newest first, in the references' order."""
    found: list[str] = []
    for reference in references:
        named = [report for report in published if report == reference or report.startswith(f"{reference}:")]
        found += [report for report in sorted(named, reverse=True) if report not in found]
    return tuple(found)


class KeyedDataset(Protocol):
    """What links need of a dataset: which it is, and its source's industry."""

    @property
    def id(self) -> str: ...

    @property
    def source(self) -> str: ...

    @property
    def industry(self) -> str | None: ...


@dataclass(frozen=True)
class DatasetKey:
    id: str
    source: str
    industry: str | None


@dataclass(frozen=True)
class PublishedIndustry:
    source: str
    name: str  # as the source names it
    register: str | None
    governed_by: tuple[str, ...]  # its register's regulations, or its own
    reports: tuple[str, ...]
    datasets: tuple[str, ...]


@dataclass(frozen=True)
class SectorDefinition:
    """One curated industry across the sources' own names, e.g. sharia banking: OJK's BUS and BPRS."""

    id: str
    name: str
    name_en: str
    industries: tuple[tuple[str, str], ...]  # (source, the industry as that source names it)


@dataclass(frozen=True)
class PublishedSector:
    """A sector with everything its industries link: where a market question meets the law and the reports."""

    id: str
    name: str
    name_en: str
    industries: tuple[Mapping[str, str], ...]  # source, name
    registers: tuple[str, ...]
    governed_by: tuple[str, ...]
    reports: tuple[str, ...]
    datasets: tuple[str, ...]


def industries(
    links: Sequence[IndustryLink],
    datasets: Sequence[KeyedDataset],
    governed_by: Mapping[str, tuple[str, ...]],
    published_reports: Sequence[str],
) -> tuple[PublishedIndustry, ...]:
    """Each curated industry with what it links to: the bridge from a market question to the law and the reports.

    `governed_by`: each register's regulations, by register ID.
    """
    return tuple(
        PublishedIndustry(
            source=link.source,
            name=link.industry,
            register=link.register,
            governed_by=industry_regulations(link, governed_by)[1],
            reports=linked_reports(link.reports, published_reports),
            datasets=tuple(sorted(d.id for d in datasets if d.source == link.source and d.industry == link.industry)),
        )
        for link in links
    )


def sectors(
    definitions: Sequence[SectorDefinition], published: Sequence[PublishedIndustry]
) -> tuple[PublishedSector, ...]:
    """Each sector with its industries' registers, regulations, reports and datasets, each once, in its industries'
    order. An industry no source names any more is kept in the sector and adds nothing."""
    by_key = {(industry.source, industry.name): industry for industry in published}

    def sector(definition: SectorDefinition) -> PublishedSector:
        found = [by_key[member] for member in definition.industries if member in by_key]

        def gathered(values: Callable[[PublishedIndustry], Sequence[str]]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(value for industry in found for value in values(industry)))

        return PublishedSector(
            id=definition.id,
            name=definition.name,
            name_en=definition.name_en,
            industries=tuple({"source": source, "name": name} for source, name in definition.industries),
            registers=gathered(lambda industry: (industry.register,) if industry.register else ()),
            governed_by=gathered(lambda industry: industry.governed_by),
            reports=gathered(lambda industry: industry.reports),
            datasets=gathered(lambda industry: industry.datasets),
        )

    return tuple(sector(definition) for definition in definitions)


def linked_datasets(
    datasets: Sequence[PublishedDataset], links: Sequence[IndustryLink], published_reports: Sequence[str]
) -> tuple[PublishedDataset, ...]:
    """Each dataset with the published reports its industry's curated links name."""
    return tuple(replace(dataset, reports=_dataset_reports(dataset, links, published_reports)) for dataset in datasets)


def with_links(
    publication: MarketPublication,
    registers: Sequence[RegisterInfo],
    links: Sequence[IndustryLink],
    definitions: Sequence[SectorDefinition] = (),
) -> MarketPublication:
    """The publication with each register's and dataset's reports, the industries and the sectors, from the curated
    links."""
    published = [report.id for report in publication.reports.reports]
    by_register = {register.id: register.reports for register in registers}
    statistics = publication.statistics
    datasets = linked_datasets(statistics.datasets, links, published)
    published_industries = industries(links, datasets, {r.id: r.governed_by for r in registers}, published)
    return replace(
        publication,
        registers=tuple(replace(register, reports=linked_reports(by_register.get(register.id, ()), published))
                        for register in publication.registers),
        statistics=replace(statistics, datasets=datasets),
        industries=published_industries,
        sectors=sectors(definitions, published_industries),
    )


@dataclass(frozen=True)
class RegisterLinksRow:
    id: str
    governed_by: tuple[str, ...]
    reports: tuple[str, ...]


@dataclass(frozen=True)
class DatasetLinks:
    """What a dataset's curated links decide; the rest of it comes from its series."""

    id: str
    register: str | None
    governed_by: tuple[str, ...]
    reports: tuple[str, ...]
    citation: str | None


@dataclass(frozen=True)
class Relinked:
    registers: tuple[RegisterLinksRow, ...]
    datasets: tuple[DatasetLinks, ...]
    industries: tuple[PublishedIndustry, ...]
    sectors: tuple[PublishedSector, ...]


def relinked(
    datasets: Sequence[KeyedDataset],
    registers: Sequence[RegisterInfo],
    links: Sequence[IndustryLink],
    citations: Mapping[str, str],
    published_reports: Sequence[str],
    definitions: Sequence[SectorDefinition],
) -> Relinked:
    """Everything the curated links decide in published_market, for the datasets published: what a full publish
    would give, without reading a series. `citations`: how each source asks to be cited."""
    governed_by = {register.id: register.governed_by for register in registers}
    by_industry = {(link.source, link.industry): link for link in links}
    published_industries = industries(links, datasets, governed_by, published_reports)
    return Relinked(
        registers=tuple(RegisterLinksRow(r.id, r.governed_by, linked_reports(r.reports, published_reports))
                        for r in registers),
        datasets=tuple(
            DatasetLinks(d.id, *industry_regulations(by_industry.get((d.source, d.industry)) if d.industry else None,
                                                     governed_by),
                         _dataset_reports(d, links, published_reports), citations.get(d.source))
            for d in datasets
        ),
        industries=published_industries,
        sectors=sectors(definitions, published_industries),
    )


def _dataset_reports(
    dataset: KeyedDataset, links: Sequence[IndustryLink], published_reports: Sequence[str]
) -> tuple[str, ...]:
    by_industry = {(link.source, link.industry): link.reports for link in links}
    return linked_reports(by_industry.get((dataset.source, dataset.industry), ()), published_reports)
