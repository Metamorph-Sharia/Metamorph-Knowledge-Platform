"""Publish the market data layer: published_market is rebuilt whole from the records held.

A register's records are few (hundreds), and a company or a standing depends on every record of its register,
so a whole rebuild in one transaction is simpler than tracking what changed, and never half-applied. Series,
reports and releases are rebuilt in the same transaction, so a reader never sees parts from different publishes.
Passages are cut again from each text every time, and what they name found again, so a better rule needs no new
reading of a PDF or a page.

Series are millions of values (BPS), so they are read and written in parts of whole datasets inside the same
transaction: a publish holds one part, never the corpus. Measured 2026-10-29 on 238,601 series: about 5.2 GB held
whole, 460 MB in parts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from metamorph_market import ReportRecord

from metamorph_platform.application.ports import BlobReader, MarketSource, PublishedMarketStore, PublishedMarketWriter
from metamorph_platform.domain.market.links import linked_datasets, with_links
from metamorph_platform.domain.market.mentions import Passage, mentions
from metamorph_platform.domain.market.publication import RegisterInfo, publication
from metamorph_platform.domain.market.releases import Releases, releases
from metamorph_platform.domain.market.reports import Reports, reports
from metamorph_platform.domain.market.statistics import (
    IndustryLink,
    PublishedDataset,
    Statistics,
    in_datasets,
    statistics,
)

SERIES_PER_PART = 5_000  # whole datasets, so a part can be larger: BPS's largest holds about 10,000 series


@dataclass(frozen=True)
class MarketPublishReport:
    registers: int
    editions: int
    companies: int
    entities: int
    datasets: int = 0
    series: int = 0
    observations: int = 0
    reports: int = 0
    passages: int = 0
    held_back: int = 0  # reports and releases without text
    releases: int = 0
    release_passages: int = 0
    mentions: int = 0


class PublishMarket:
    def __init__(
        self, source: MarketSource, published: PublishedMarketStore, blobs: BlobReader,
        series_per_part: int = SERIES_PER_PART,
    ) -> None:
        self.source = source
        self.published = published
        self.blobs = blobs  # reports' texts; a release's words travel in its record
        self.series_per_part = series_per_part

    def run(self) -> MarketPublishReport:
        keys = self.source.storage_keys()
        records = self.source.current_reports()
        cut = reports(records, self._texts(records, keys), keys)
        announced = releases(self.source.current_releases(), keys)
        with self.published.replacing() as writer:  # the curated links are read under the publish lock
            registers, links = self.source.register_infos(), self.source.industry_links()
            built = publication(registers, self.source.current_records(), keys)
            named = mentions(_passages(cut, announced), built.companies)
            datasets, series, observations = self._add_statistics(writer, registers, links, cut, keys)
            whole = replace(built, statistics=Statistics(datasets, (), ()), reports=cut, releases=announced,
                            mentions=tuple(named))
            writer.add(with_links(whole, registers, links, self.source.sector_definitions()))
        return MarketPublishReport(
            len(built.registers), len(built.editions), len(built.companies), len(built.entities),
            len(datasets), series, observations,
            len(cut.reports), len(cut.passages), len(cut.held_back) + len(announced.held_back),
            len(announced.releases), len(announced.passages), len(named),
        )

    def _add_statistics(
        self, writer: PublishedMarketWriter, registers: list[RegisterInfo], links: list[IndustryLink], cut: Reports,
        keys: dict[str, str],
    ) -> tuple[tuple[PublishedDataset, ...], int, int]:
        """Each part of whole datasets, linked to its reports, written before the next is read; the datasets and the
        counts of series and observations written."""
        governed_by = {register.id: register.governed_by for register in registers}
        published_reports = [report.id for report in cut.reports]
        citations = self.source.citations()
        datasets: list[PublishedDataset] = []
        series = observations = 0
        for records in in_datasets(self.source.current_series(), self.series_per_part):
            part = statistics(links, governed_by, records, keys, citations)
            part = replace(part, datasets=linked_datasets(part.datasets, links, published_reports))
            writer.add_statistics(part)
            datasets += part.datasets
            series, observations = series + len(part.series), observations + len(part.observations)
        return tuple(datasets), series, observations

    def _texts(self, records: list[ReportRecord], keys: dict[str, str]) -> dict[str, str]:
        """Each report's text by its sha256; one not kept in the object store is left out, so held back."""
        kept = {record.text.file: keys[record.text.file] for record in records if record.text.file in keys}
        return {sha: self.blobs.read(key).decode("utf-8") for sha, key in kept.items()}


def _passages(cut: Reports, announced: Releases) -> list[Passage]:
    """Every passage of every report and release, for what it names."""
    return ([Passage("report", p.report, p.address, p.text) for p in cut.passages]
            + [Passage("release", p.release, p.address, p.text) for p in announced.passages])
