"""Publish the market data layer: published_market is rebuilt whole from the records held.

A register's records are few (hundreds), and a company or a standing depends on every record of its register,
so a whole rebuild in one transaction is simpler than tracking what changed, and never half-applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from metamorph_platform.application.ports import MarketSource, PublishedMarketStore
from metamorph_platform.domain.market.publication import publication


@dataclass(frozen=True)
class MarketPublishReport:
    registers: int
    editions: int
    companies: int
    entities: int


class PublishMarket:
    def __init__(self, source: MarketSource, published: PublishedMarketStore) -> None:
        self.source = source
        self.published = published

    def run(self) -> MarketPublishReport:
        built = publication(self.source.register_infos(), self.source.current_records(), self.source.storage_keys())
        self.published.replace_all(built)
        return MarketPublishReport(len(built.registers), len(built.editions), len(built.companies), len(built.entities))
