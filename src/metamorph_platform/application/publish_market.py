"""Publish the market data layer: published_market is rebuilt whole from the records held.

A register's records are few (hundreds), and a company or a standing depends on every record of its register,
so a whole rebuild in one transaction is simpler than tracking what changed, and never half-applied. Series and
reports are rebuilt in the same transaction, so a reader never sees parts from different publishes. A report's
passages are cut again from its text each time, so a better rule needs no new reading of a PDF.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from metamorph_market import ReportRecord

from metamorph_platform.application.ports import BlobReader, MarketSource, PublishedMarketStore
from metamorph_platform.domain.market.links import with_links
from metamorph_platform.domain.market.publication import publication
from metamorph_platform.domain.market.reports import reports
from metamorph_platform.domain.market.statistics import statistics


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
    held_back: int = 0  # reports without text


class PublishMarket:
    def __init__(self, source: MarketSource, published: PublishedMarketStore, blobs: BlobReader) -> None:
        self.source = source
        self.published = published
        self.blobs = blobs  # reports' texts

    def run(self) -> MarketPublishReport:
        registers, keys = self.source.register_infos(), self.source.storage_keys()
        built = publication(registers, self.source.current_records(), keys)
        governed_by = {register.id: register.governed_by for register in registers}
        links = self.source.industry_links()
        found = statistics(links, governed_by, self.source.current_series(), keys, self.source.citations())
        records = self.source.current_reports()
        cut = reports(records, self._texts(records, keys), keys)
        self.published.replace_all(with_links(replace(built, statistics=found, reports=cut), registers, links))
        return MarketPublishReport(
            len(built.registers), len(built.editions), len(built.companies), len(built.entities),
            len(found.datasets), len(found.series), len(found.observations),
            len(cut.reports), len(cut.passages), len(cut.held_back),
        )

    def _texts(self, records: list[ReportRecord], keys: dict[str, str]) -> dict[str, str]:
        """Each report's text by its sha256; one not kept in the object store is left out, so held back."""
        kept = {record.text.file: keys[record.text.file] for record in records if record.text.file in keys}
        return {sha: self.blobs.read(key).decode("utf-8") for sha, key in kept.items()}
