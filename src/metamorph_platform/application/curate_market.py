"""The Metamorph team's changes to the market layer's curated links, each published as it is made.

A change is checked first (domain/market/curation.py) and needs a reason. Then it is written with its audit row and
published by a links-only publish (RelinkMarket), in one transaction, so published_market never disagrees with the
record of a change. The answer warns about what the links name that is not published: kept, and said.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from metamorph_platform.application.ports import Curator, MarketCurationActions, PublishedNames
from metamorph_platform.domain.curation import checked_reason
from metamorph_platform.domain.market.curation import (
    industry_link,
    link_warnings,
    register_links,
    sector_definition,
    source_settings,
)

Warnings = tuple[str, ...]


class Relink(Protocol):
    def run(self) -> None: ...


class CurateMarket:
    def __init__(self, actions: MarketCurationActions, published: PublishedNames, relink: Relink) -> None:
        self.actions = actions
        self.published = published
        self.relink = relink

    def set_register_links(
        self, curator: Curator, register_id: str, governed_by: Sequence[str], reports: Sequence[str], fresh_days: int,
        reason: str,
    ) -> Warnings:
        links, why = register_links(governed_by, reports, fresh_days), checked_reason(reason)
        with self.actions.atomically():
            self.actions.set_register_links(curator, register_id, links, why)
            self.relink.run()
        return self._warnings(links.governed_by, links.reports)

    def set_industry(
        self, curator: Curator, source: str, name: str, register: str | None, governed_by: Sequence[str],
        reports: Sequence[str], reason: str,
    ) -> Warnings:
        link, why = industry_link(source, name, register, governed_by, reports), checked_reason(reason)
        with self.actions.atomically():
            self.actions.set_industry(curator, link, why)
            self.relink.run()
        return self._warnings(link.governed_by, link.reports)

    def withdraw_industry(self, curator: Curator, source: str, name: str, reason: str) -> Warnings:
        why = checked_reason(reason)
        with self.actions.atomically():
            self.actions.withdraw_industry(curator, source, name, why)
            self.relink.run()
        return ()

    def set_source(
        self, curator: Curator, source_id: str, citation: str, fresh_days: int, download_page: str, download_hint: str,
        reason: str,
    ) -> Warnings:
        settings, why = source_settings(citation, fresh_days, download_page, download_hint), checked_reason(reason)
        with self.actions.atomically():
            self.actions.set_source(curator, source_id, settings, why)
            self.relink.run()
        return ()

    def set_sector(
        self, curator: Curator, sector_id: str, name: str, name_en: str, industries: Sequence[tuple[str, str]],
        reason: str,
    ) -> Warnings:
        sector, why = sector_definition(sector_id, name, name_en, industries), checked_reason(reason)
        with self.actions.atomically():
            self.actions.set_sector(curator, sector, why)
            self.relink.run()
        return ()

    def withdraw_sector(self, curator: Curator, sector_id: str, reason: str) -> Warnings:
        why = checked_reason(reason)
        with self.actions.atomically():
            self.actions.withdraw_sector(curator, sector_id, why)
            self.relink.run()
        return ()

    def _warnings(self, governed_by: tuple[str, ...], reports: tuple[str, ...]) -> Warnings:
        return link_warnings(governed_by, reports, published_documents=self.published.documents(list(governed_by)),
                             published_reports=self.published.reports())
