"""Curated links between reports and the rest of the market layer, resolved against what is published.

A register or an industry names its reports in market.register.reports and market.industry.reports, each a report
ID (ojk:roadmap:2023:rp3si) or a family (ojk:lpksi), which names every edition published: a new edition is linked
without curating it. A link to a report not published names nothing. Curated, never inferred.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from metamorph_platform.domain.market.statistics import IndustryLink, PublishedDataset

if TYPE_CHECKING:
    from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo


def linked_reports(references: Sequence[str], published: Sequence[str]) -> tuple[str, ...]:
    """The published reports the references name: each family's editions newest first, in the references' order."""
    found: list[str] = []
    for reference in references:
        named = [report for report in published if report == reference or report.startswith(f"{reference}:")]
        found += [report for report in sorted(named, reverse=True) if report not in found]
    return tuple(found)


@dataclass(frozen=True)
class PublishedIndustry:
    source: str
    name: str  # as the source names it
    register: str | None
    governed_by: tuple[str, ...]  # its register's regulations, or its own
    reports: tuple[str, ...]
    datasets: tuple[str, ...]


def industries(
    links: Sequence[IndustryLink],
    datasets: Sequence[PublishedDataset],
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
            governed_by=governed_by.get(link.register, ()) if link.register else link.governed_by,
            reports=linked_reports(link.reports, published_reports),
            datasets=tuple(sorted(d.id for d in datasets if d.source == link.source and d.industry == link.industry)),
        )
        for link in links
    )


def with_links(
    publication: MarketPublication, registers: Sequence[RegisterInfo], links: Sequence[IndustryLink]
) -> MarketPublication:
    """The publication with each register's and dataset's reports, and the industries, from the curated links."""
    published = [report.id for report in publication.reports.reports]
    by_register = {register.id: register.reports for register in registers}
    by_industry = {(link.source, link.industry): link.reports for link in links}
    statistics = publication.statistics
    datasets = tuple(
        replace(dataset, reports=linked_reports(by_industry.get((dataset.source, dataset.industry), ()), published))
        for dataset in statistics.datasets
    )
    return replace(
        publication,
        registers=tuple(replace(register, reports=linked_reports(by_register.get(register.id, ()), published))
                        for register in publication.registers),
        statistics=replace(statistics, datasets=datasets),
        industries=industries(links, datasets, {r.id: r.governed_by for r in registers}, published),
    )

