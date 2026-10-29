"""Press releases cut into passages: what a regulator announced, in its own words, on its date
(market-data-layer-plan.md, Phase 5).

A release is cut by reports' rule (reports.py), without pages: a release is a page or two of HTML. It is cited by
its issuer, its number when it has one, and its date. A release has no legal force: one announcing a regulation is
not the regulation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from metamorph_market import ReleaseRecord

from metamorph_platform.domain.dates import MONTHS
from metamorph_platform.domain.market.reports import unpaged_passages


@dataclass(frozen=True)
class PublishedRelease:
    id: str
    issuer: str
    number: str | None  # as printed
    title: str  # as listed
    published_on: str  # ISO date
    language: str
    url: str | None  # its page
    citation: str
    passages: int
    storage_key: str | None  # its body as published, in the object store


@dataclass(frozen=True)
class PublishedReleasePassage:
    release: str
    address: str
    ordinal: int
    text: str
    words: int


@dataclass(frozen=True)
class Releases:
    releases: tuple[PublishedRelease, ...] = ()  # newest first
    passages: tuple[PublishedReleasePassage, ...] = ()
    held_back: tuple[str, ...] = ()  # releases with no words: material corruption


def releases(records: Sequence[ReleaseRecord], keys: Mapping[str, str]) -> Releases:
    """`keys`: where each file is kept in the object store."""
    published, cut, held_back = [], [], []
    for record in sorted(records, key=lambda found: (found.release.published_on, found.release.id), reverse=True):
        found = unpaged_passages(record.text)
        if not found:
            held_back.append(record.release.id)
            continue
        published.append(_published(record, len(found), keys))
        cut += [PublishedReleasePassage(record.release.id, p.address, p.ordinal, p.text, p.words) for p in found]
    return Releases(tuple(published), tuple(cut), tuple(held_back))


def citation(issuer: str, number: str | None, published_on: str) -> str:
    day = date.fromisoformat(published_on)
    numbered = f" {number}" if number else ""
    return f"Siaran Pers {issuer.upper()}{numbered}, {day.day} {MONTHS[day.month - 1].capitalize()} {day.year}"


def _published(record: ReleaseRecord, passages: int, keys: Mapping[str, str]) -> PublishedRelease:
    release = record.release
    return PublishedRelease(
        id=release.id,
        issuer=release.issuer,
        number=release.number,
        title=release.title,
        published_on=release.published_on,
        language=release.language,
        url=record.source.url,
        citation=citation(release.issuer, release.number, release.published_on),
        passages=passages,
        storage_key=keys.get(record.files[0].sha256),
    )
