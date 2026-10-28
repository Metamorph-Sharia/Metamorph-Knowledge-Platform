"""What loading a market record needs decided: whether it changed, whether it belongs where the platform knows,
and which files to keep.

Registers and statistics sources are curated (market.register, market.statistics_source): a record on another one
waits in quarantine until it is added. A report belongs to no register or source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Set

from metamorph_market import LicensedEntityRecord, MarketRecord, ReportRecord, to_json

from metamorph_platform.domain.market.statistics import source_of


def market_package_hash(record: MarketRecord) -> str:
    """Identical records hash identically, so an unchanged line is recognised and skipped."""
    return hashlib.sha256(to_json(record).encode("utf-8")).hexdigest()


TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"


def kept_files(record: MarketRecord) -> dict[str, str]:
    """Every file the record points at, by sha256, with its media type: a report's text as well as its PDF."""
    files = {file.sha256: file.media_type for file in record.files}
    if isinstance(record, ReportRecord):
        files[record.text.file] = TEXT_MEDIA_TYPE
    return files


def unknown_scope_problems(record: MarketRecord, registers: Set[str], sources: Set[str]) -> list[str]:
    if isinstance(record, ReportRecord):
        return []
    if isinstance(record, LicensedEntityRecord):
        register = record.entity.register
        return [] if register in registers else [f"entity.register: {register!r} is not a register the platform knows"]
    source = source_of(record.series.dataset)
    return [] if source in sources else [f"series.dataset: {source!r} is not a statistics source the platform knows"]
