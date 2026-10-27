"""What loading a market record needs decided: whether it changed, and whether its register is known."""

from __future__ import annotations

import hashlib
from collections.abc import Set

from metamorph_market import LicensedEntityRecord, to_json


def market_package_hash(record: LicensedEntityRecord) -> str:
    """Identical records hash identically, so an unchanged line is recognised and skipped."""
    return hashlib.sha256(to_json(record).encode("utf-8")).hexdigest()


def register_problems(record: LicensedEntityRecord, known: Set[str]) -> list[str]:
    """A register is curated (market.register): a record on another one waits in quarantine until it is added."""
    register = record.entity.register
    return [] if register in known else [f"entity.register: {register!r} is not a register the platform knows"]
