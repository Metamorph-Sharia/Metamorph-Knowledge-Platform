"""The published catalogue: every regulation the platform publishes, for the services that list and browse them
(MIRA's regulatory catalogue). It reads only the `published` schema (docs/published-schema.md), so a document that is
held, suppressed or never published can't appear: the catalogue is what the assistant may cite, nothing more.

A page lists regulations newest first, a fixed number at a time, with an opaque cursor for the next. Newest is by the
day the regulation was made: promulgated, else enacted, else the first day of the year its number names, else the day
it takes effect; one with none of these comes last. The facets count what each filter would leave, each counted with
every other filter applied but its own, as a faceted search does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

PAGE_SIZE = 25
MOST_PER_PAGE = 100
CATALOGUE_FACETS = ("issuer", "family", "year", "status", "kind")


@dataclass(frozen=True)
class CatalogueFilters:
    """What narrows the catalogue. An empty value narrows nothing."""

    query: str = ""  # words in the citation, title, an alias or the ID
    issuer: str = ""
    family: str = ""
    year: int | None = None
    status: str = ""
    kind: str = ""


@dataclass(frozen=True)
class CatalogueEntry:
    id: str  # the canonical ID, e.g. ojk:pojk:2020:47
    citation: str
    title: str
    kind: str
    issuer: str
    family: str
    number: str
    year: int | None  # the year its number names
    status: str
    promulgated_on: date | None
    effective_on: date | None


@dataclass(frozen=True)
class CataloguePage:
    entries: tuple[CatalogueEntry, ...]
    total: int  # how many the filters leave, across every page
    next_cursor: str | None  # None on the last page


@dataclass(frozen=True)
class FacetCount:
    value: str
    count: int


@dataclass(frozen=True)
class CatalogueFacets:
    total: int
    issuers: tuple[FacetCount, ...]
    families: tuple[FacetCount, ...]
    years: tuple[FacetCount, ...]  # newest first
    statuses: tuple[FacetCount, ...]
    kinds: tuple[FacetCount, ...]


class InvalidCursor(ValueError):
    """A cursor this catalogue didn't give, or one from a different set of filters."""


class PublishedCatalogue(Protocol):
    def page(self, filters: CatalogueFilters, cursor: str | None, limit: int) -> CataloguePage:
        """Raises InvalidCursor for a cursor it didn't give."""

    def facets(self, filters: CatalogueFilters) -> CatalogueFacets: ...


def page_size(limit: int | None) -> int:
    """The number of entries a page holds: the default when none is asked for, and never more than the most."""
    return PAGE_SIZE if not limit or limit < 1 else min(limit, MOST_PER_PAGE)
