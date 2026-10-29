"""What a curator may set in the market layer's curated links, checked before anything is written.

The links are reference data no connector sends: a register's or an industry's regulations and reports, a statistics
source's citation and freshness, and sectors, one curated list of industries across the sources' own names. A link is
checked by its form here. Whether what it names is published is a warning, never a refusal: a link to a document not
published yet links nothing until it is, as links to reports already do.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from metamorph_contract import is_canonical

from metamorph_platform.domain.curation import InvalidCorrection
from metamorph_platform.domain.market.links import SectorDefinition, linked_reports
from metamorph_platform.domain.market.statistics import IndustryLink

REPORT_REFERENCE = re.compile(r"^[a-z0-9]+:[a-z0-9]+(:[a-z0-9][a-z0-9._-]*){0,2}$")  # an ID, or a family: ojk:lpksi
SECTOR_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
WEB_ADDRESS = re.compile(r"^https?://\S+$")
MAX_FRESH_DAYS = 3650


@dataclass(frozen=True)
class RegisterLinks:
    governed_by: tuple[str, ...]  # the regulations its licences are granted under
    reports: tuple[str, ...]
    fresh_days: int  # health warns when its newest edition is older


@dataclass(frozen=True)
class SourceSettings:
    citation: str | None  # how the source asks to be cited
    fresh_days: int  # health warns when its newest period ended longer ago
    download_page: str | None  # where a curator downloads an edition by hand (SEKI)
    download_hint: str | None  # what to download there, and where it goes


def register_links(governed_by: Sequence[str], reports: Sequence[str], fresh_days: int) -> RegisterLinks:
    return RegisterLinks(_documents(governed_by), _reports(reports), _fresh_days(fresh_days))


def industry_link(
    source: str, name: str, register: str | None, governed_by: Sequence[str], reports: Sequence[str]
) -> IndustryLink:
    """An industry links a register, whose regulations it then shares, or regulations of its own: not both, since a
    register's would hide its own."""
    industry = _required(name, "name the industry as its source does")
    regulations = _documents(governed_by)
    if register and regulations:
        raise InvalidCorrection("an industry takes a register's regulations, or its own: not both")
    return IndustryLink(source, industry, register or None, regulations, _reports(reports))


def source_settings(citation: str, fresh_days: int, download_page: str, download_hint: str) -> SourceSettings:
    page = download_page.strip()
    if page and not WEB_ADDRESS.match(page):
        raise InvalidCorrection(f"the download page must be a web address (https://…), not {page}")
    return SourceSettings(_optional(citation), _fresh_days(fresh_days), page or None, _optional(download_hint))


def sector_definition(
    sector_id: str, name: str, name_en: str, industries: Sequence[tuple[str, str]]
) -> SectorDefinition:
    if not SECTOR_ID.match(sector_id):
        raise InvalidCorrection(f"a sector's ID is lowercase words joined by hyphens, e.g. sharia-banking: {sector_id}")
    members = tuple(dict.fromkeys((source, " ".join(industry.split())) for source, industry in industries))
    if not members:
        raise InvalidCorrection("a sector gathers at least one industry")
    return SectorDefinition(sector_id, _required(name, "name the sector"), " ".join(name_en.split()), members)


def link_warnings(
    governed_by: Sequence[str],
    reports: Sequence[str],
    *,
    published_documents: Collection[str],
    published_reports: Sequence[str],
) -> tuple[str, ...]:
    """What the links name that is not published: kept, and said."""
    return (
        *(f"{document} is not published: it links nothing until it is"
          for document in governed_by if document not in published_documents),
        *(f"{report} names no published report: it links nothing until one is"
          for report in reports if not linked_reports([report], published_reports)),
    )


def _documents(ids: Sequence[str]) -> tuple[str, ...]:
    found = _distinct(ids)
    for document in found:
        if not is_canonical(document):
            raise InvalidCorrection(f"{document} is not a document ID, such as ojk:pojk:2024:40")
    return found


def _reports(references: Sequence[str]) -> tuple[str, ...]:
    found = _distinct(references)
    for report in found:
        if not REPORT_REFERENCE.match(report):
            raise InvalidCorrection(f"{report} is not a report ID or family, such as ojk:lpksi:2025 or ojk:lpksi")
    return found


def _fresh_days(days: int) -> int:
    if not 1 <= days <= MAX_FRESH_DAYS:
        raise InvalidCorrection(f"fresh_days must be between 1 and {MAX_FRESH_DAYS}")
    return days


def _distinct(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _required(text: str, missing: str) -> str:
    value = " ".join(text.split())
    if not value:
        raise InvalidCorrection(missing)
    return value


def _optional(text: str) -> str | None:
    return " ".join(text.split()) or None
