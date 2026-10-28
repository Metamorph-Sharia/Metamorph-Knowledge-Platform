"""Publish the market data layer: published_market is rebuilt whole from the records held.

A register's records are few (hundreds), and a company or a standing depends on every record of its register,
so a whole rebuild in one transaction is simpler than tracking what changed, and never half-applied. Series are
rebuilt in the same transaction, so a reader never sees registers and statistics from different publishes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from metamorph_platform.application.ports import MarketSource, PublishedMarketStore
from metamorph_platform.domain.market.publication import publication
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


class PublishMarket:
    def __init__(self, source: MarketSource, published: PublishedMarketStore) -> None:
        self.source = source
        self.published = published

    def run(self) -> MarketPublishReport:
        registers, keys = self.source.register_infos(), self.source.storage_keys()
        built = publication(registers, self.source.current_records(), keys)
        governed_by = {register.id: register.governed_by for register in registers}
        found = statistics(self.source.industry_links(), governed_by, self.source.current_series(), keys,
                           self.source.citations())
        self.published.replace_all(replace(built, statistics=found))
        return MarketPublishReport(
            len(built.registers), len(built.editions), len(built.companies), len(built.entities),
            len(found.datasets), len(found.series), len(found.observations),
        )
