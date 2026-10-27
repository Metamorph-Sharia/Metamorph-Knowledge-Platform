"""A license's standing on its register, and what each edition of the register changed.

The connector reports which editions list a license; standing is derived here, the same way for every register
(docs/market-data-layer-plan.md): a license missing from the newest edition left after the last edition that
listed it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from metamorph_market import BusinessType, LicenseKind


@dataclass(frozen=True)
class HeldLicense:
    """One license or registration as the platform holds it: what its standing and company are derived from."""

    id: str  # "ojk:lpbbti:kep-49-d.05-2017"
    register: str
    kind: LicenseKind
    business_type: BusinessType
    editions: tuple[date, ...]  # every edition that lists it, oldest first
    legal_names: tuple[str, ...]  # as listed, oldest first


@dataclass(frozen=True)
class Standing:
    first_listed: date
    last_listed: date
    on_newest_list: bool
    left_after: date | None  # the last edition that listed it, once a newer edition doesn't


@dataclass(frozen=True)
class EditionChange:
    edition: date
    listed: int
    joined: int  # listed here, not in the edition before
    left: int  # listed in the edition before, not here


def standing(license_: HeldLicense, newest: date) -> Standing:
    first, last = license_.editions[0], license_.editions[-1]
    on_newest = last == newest
    return Standing(first, last, on_newest, None if on_newest else last)


def edition_changes(licenses: Sequence[HeldLicense]) -> list[EditionChange]:
    """Per edition, oldest first: listed = the edition before's listed + joined − left, by construction."""
    listed: dict[date, set[str]] = {}
    for license_ in licenses:
        for edition in license_.editions:
            listed.setdefault(edition, set()).add(license_.id)
    changes, before = [], set()
    for edition in sorted(listed):
        now = listed[edition]
        changes.append(EditionChange(edition, len(now), len(now - before), len(before - now)))
        before = now
    return changes


def review_notes(license_: HeldLicense) -> tuple[str, ...]:
    """What a reader should know is unclear. A note never holds a license back: only a record the contract
    rejects is kept out, in quarantine."""
    notes = []
    if license_.business_type is BusinessType.UNKNOWN:
        notes.append("business type unknown")
    if license_.kind is LicenseKind.UNKNOWN:
        notes.append("license kind unknown")
    return tuple(notes)
