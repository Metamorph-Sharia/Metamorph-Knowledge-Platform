"""What loading a market record needs decided: whether it changed, and whether it belongs where the platform knows.

Registers and statistics sources are curated (market.register, market.statistics_source): a record on another one
waits in quarantine until it is added.
"""

from __future__ import annotations

import hashlib
from collections.abc import Set

from metamorph_market import LicensedEntityRecord, MarketRecord, to_json

from metamorph_platform.domain.market.statistics import source_of


def market_package_hash(record: MarketRecord) -> str:
    """Identical records hash identically, so an unchanged line is recognised and skipped."""
    return hashlib.sha256(to_json(record).encode("utf-8")).hexdigest()


def unknown_scope_problems(record: MarketRecord, registers: Set[str], sources: Set[str]) -> list[str]:
    if isinstance(record, LicensedEntityRecord):
        register = record.entity.register
        return [] if register in registers else [f"entity.register: {register!r} is not a register the platform knows"]
    source = source_of(record.series.dataset)
    return [] if source in sources else [f"series.dataset: {source!r} is not a statistics source the platform knows"]
