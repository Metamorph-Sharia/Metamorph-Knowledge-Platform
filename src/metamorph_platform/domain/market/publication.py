"""published_market, built from the market records: plain rows, so publishing is a pure function.

Each register's newest edition is the newest any of its records lists. A company's values are its newest
record's; its names are every other name its records were listed under.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from metamorph_market import LicensedEntityRecord, Listing

from metamorph_platform.domain.market.companies import Company, companies
from metamorph_platform.domain.market.history import HeldLicense, edition_changes, review_notes, standing
from metamorph_platform.domain.market.links import PublishedIndustry, PublishedSector
from metamorph_platform.domain.market.releases import Releases
from metamorph_platform.domain.market.reports import Reports
from metamorph_platform.domain.market.statistics import Statistics

if TYPE_CHECKING:
    from metamorph_platform.domain.market.mentions import Mention  # mentions find published companies


@dataclass(frozen=True)
class RegisterInfo:
    """A register as curated in market.register."""

    id: str
    issuer: str
    name: str
    governed_by: tuple[str, ...]
    reports: tuple[str, ...] = ()  # its reports: IDs, or families (ojk:lpksi) for every edition


@dataclass(frozen=True)
class PublishedRegister:
    id: str
    issuer: str
    name: str
    governed_by: tuple[str, ...]
    newest_edition: date | None
    editions: int
    reports: tuple[str, ...] = ()  # the published reports its curated links name


@dataclass(frozen=True)
class PublishedEdition:
    register: str
    edition: date
    listed: int
    joined: int
    left: int
    sha256: str | None
    source_url: str | None
    storage_key: str | None


@dataclass(frozen=True)
class PublishedCompany:
    id: str
    register: str
    legal_name: str
    names: tuple[str, ...]
    business_type: str
    status: str
    first_listed: date
    left_after: date | None


@dataclass(frozen=True)
class PublishedEntity:
    id: str
    company_id: str
    register: str
    kind: str
    license_number: str
    license_date: date | None
    legal_name: str
    names: tuple[str, ...]
    business_type: str
    website: str | None
    channels: tuple[str, ...]
    first_listed: date
    last_listed: date
    on_newest_list: bool
    left_after: date | None
    review_notes: tuple[str, ...]


@dataclass(frozen=True)
class PublishedListing:
    entity_id: str
    edition: date
    legal_name: str
    page: int
    row_number: int
    cells: Mapping[str, Any]


@dataclass(frozen=True)
class MarketPublication:
    registers: tuple[PublishedRegister, ...]
    editions: tuple[PublishedEdition, ...]
    companies: tuple[PublishedCompany, ...]
    entities: tuple[PublishedEntity, ...]
    listings: tuple[PublishedListing, ...]
    statistics: Statistics = field(default_factory=lambda: Statistics((), (), ()))
    reports: Reports = field(default_factory=Reports)
    industries: tuple[PublishedIndustry, ...] = ()
    releases: Releases = field(default_factory=Releases)
    mentions: tuple[Mention, ...] = ()  # what each passage of a report or a release names
    sectors: tuple[PublishedSector, ...] = ()  # curated industries across sources (market.sector)


def publication(
    registers: Sequence[RegisterInfo], records: Sequence[LicensedEntityRecord], storage_keys: Mapping[str, str]
) -> MarketPublication:
    """`storage_keys`: where each edition file (by sha256) is kept in the object store."""
    return _combined([
        _register_publication(info, [record for record in records if record.entity.register == info.id], storage_keys)
        for info in registers
    ])


def _combined(parts: Sequence[MarketPublication]) -> MarketPublication:
    return MarketPublication(
        registers=tuple(row for part in parts for row in part.registers),
        editions=tuple(row for part in parts for row in part.editions),
        companies=tuple(row for part in parts for row in part.companies),
        entities=tuple(row for part in parts for row in part.entities),
        listings=tuple(row for part in parts for row in part.listings),
    )


def _register_publication(
    info: RegisterInfo, records: list[LicensedEntityRecord], storage_keys: Mapping[str, str]
) -> MarketPublication:
    held = {record.entity.id: _held(record) for record in records}
    newest = max((license_.editions[-1] for license_ in held.values()), default=None)
    register = PublishedRegister(info.id, info.issuer, info.name, info.governed_by, newest,
                                 len({edition for license_ in held.values() for edition in license_.editions}))
    if newest is None:
        return MarketPublication((register,), (), (), (), ())
    by_id = {record.entity.id: record for record in records}
    joined = companies(list(held.values()), newest)
    company_of = {member: company.id for company in joined for member in company.members}
    return MarketPublication(
        registers=(register,),
        editions=tuple(_editions(info.id, list(held.values()), records, storage_keys)),
        companies=tuple(_company(company, [by_id[member] for member in company.members]) for company in joined),
        entities=tuple(_entity(record, held[record.entity.id], company_of[record.entity.id], newest)
                       for record in records),
        listings=tuple(_listing(record, listing) for record in records for listing in record.listings),
    )


def _held(record: LicensedEntityRecord) -> HeldLicense:
    listings = sorted(record.listings, key=lambda listing: listing.edition)
    names = tuple(dict.fromkeys(listing.legal_name for listing in listings if listing.legal_name))
    entity = record.entity
    return HeldLicense(
        entity.id, entity.register, entity.license.kind, entity.business_type,
        tuple(date.fromisoformat(listing.edition) for listing in listings), names or (entity.legal_name,),
    )


def _editions(
    register: str, held: list[HeldLicense], records: list[LicensedEntityRecord], storage_keys: Mapping[str, str]
) -> list[PublishedEdition]:
    files = {date.fromisoformat(file.edition): file for record in records for file in record.files if file.edition}
    rows = []
    for change in edition_changes(held):
        file = files.get(change.edition)
        rows.append(PublishedEdition(
            register, change.edition, change.listed, change.joined, change.left,
            file.sha256 if file else None, file.source_url if file else None,
            storage_keys.get(file.sha256) if file else None,
        ))
    return rows


def _company(company: Company, members: list[LicensedEntityRecord]) -> PublishedCompany:
    newest = members[-1].entity
    names = [listing.legal_name for member in members for listing in member.listings]
    names += [name for member in members for name in member.entity.names]
    return PublishedCompany(
        company.id, company.register, newest.legal_name,
        tuple(name for name in dict.fromkeys(names) if name and name != newest.legal_name),
        newest.business_type.value, company.status.value, company.first_listed, company.left_after,
    )


def _entity(record: LicensedEntityRecord, held: HeldLicense, company_id: str, newest: date) -> PublishedEntity:
    entity, found = record.entity, standing(held, newest)
    return PublishedEntity(
        id=entity.id,
        company_id=company_id,
        register=entity.register,
        kind=entity.license.kind.value,
        license_number=entity.license.number,
        license_date=date.fromisoformat(entity.license.date) if entity.license.date else None,
        legal_name=entity.legal_name,
        names=entity.names,
        business_type=entity.business_type.value,
        website=entity.website,
        channels=tuple(channel.value for channel in entity.channels),
        first_listed=found.first_listed,
        last_listed=found.last_listed,
        on_newest_list=found.on_newest_list,
        left_after=found.left_after,
        review_notes=review_notes(held),
    )


def _listing(record: LicensedEntityRecord, listing: Listing) -> PublishedListing:
    return PublishedListing(record.entity.id, date.fromisoformat(listing.edition), listing.legal_name,
                            listing.page, listing.row, dict(listing.cells))
