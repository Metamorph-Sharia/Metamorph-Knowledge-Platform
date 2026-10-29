"""Publish what the curated links decide, and nothing else: after a curator changes a link, in under a second.

A full publish reads every series (minutes, on BPS's millions of values). The links decide only a few columns of
published_market: each register's regulations and reports; each dataset's register, regulations, reports and
citation; the industries and the sectors. They are rewritten in place, by the same domain functions a full publish
uses (domain/market/links.py), so the next full publish writes the same.
"""

from __future__ import annotations

from metamorph_platform.application.ports import MarketSource, PublishedMarketStore
from metamorph_platform.domain.market.links import relinked


class RelinkMarket:
    def __init__(self, source: MarketSource, published: PublishedMarketStore) -> None:
        self.source = source
        self.published = published

    def run(self) -> None:
        with self.published.relinking() as links:  # the links are read under the publish lock
            links.write(relinked(
                links.datasets(), self.source.register_infos(), self.source.industry_links(), self.source.citations(),
                links.reports(), self.source.sector_definitions(),
            ))
