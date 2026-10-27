"""What publishing makes of the market records: registers, editions, companies, entities and listings."""

from __future__ import annotations

from datetime import date

from market_platform_samples import edition_sha, licensed
from metamorph_market import BusinessType, LicenseKind

from metamorph_platform.domain.market.publication import RegisterInfo, publication

LPBBTI = RegisterInfo("ojk:lpbbti", "ojk", "LPBBTI", ("ojk:pojk:2024:40", "ojk:seojk:2025:19"))
JAN, FEB, MAR = "2021-01-31", "2021-02-28", "2021-03-31"
KEYS = {edition_sha(edition): f"blobs/{edition}" for edition in (JAN, FEB, MAR)}


def records():
    return [
        licensed("S-451/NB.213/2019", JAN, legal_name="PT Fintech Bina Bangsa", kind=LicenseKind.REGISTRATION),
        licensed("KEP-88/D.05/2021", FEB, MAR, legal_name="PT Fintech Bina Bangsa", business_type=BusinessType.SHARIA),
        licensed("KEP-1/D.05/2020", JAN, FEB, legal_name="PT Gone"),
    ]


def test_a_register_is_published_with_its_newest_edition_and_regulations() -> None:
    (register,) = publication([LPBBTI], records(), KEYS).registers

    assert (register.id, register.newest_edition, register.editions) == ("ojk:lpbbti", date(2021, 3, 31), 3)
    assert register.governed_by == ("ojk:pojk:2024:40", "ojk:seojk:2025:19")


def test_each_edition_says_what_changed_and_where_its_file_is() -> None:
    jan, feb, mar = publication([LPBBTI], records(), KEYS).editions

    assert (jan.listed, jan.joined, jan.left) == (2, 2, 0)
    assert (feb.listed, feb.joined, feb.left) == (2, 1, 1)  # the registration became a license
    assert (mar.listed, mar.joined, mar.left) == (1, 0, 1)
    assert (mar.sha256, mar.storage_key, mar.source_url) == (edition_sha(MAR), f"blobs/{MAR}", f"https://ojk.go.id/{MAR}.aspx")


def test_a_registration_and_its_license_are_one_company() -> None:
    published = publication([LPBBTI], records(), KEYS)

    fintech = next(company for company in published.companies if company.legal_name == "PT Fintech Bina Bangsa")
    assert fintech.id == "ojk:lpbbti:kep-88-d.05-2021"
    assert (fintech.status, fintech.business_type, fintech.first_listed) == ("licensed", "sharia", date(2021, 1, 31))
    members = {entity.id: entity.company_id for entity in published.entities}
    assert members["ojk:lpbbti:s-451-nb.213-2019"] == members["ojk:lpbbti:kep-88-d.05-2021"] == fintech.id


def test_an_entity_carries_its_standing_and_a_company_that_left_says_when() -> None:
    published = publication([LPBBTI], records(), KEYS)

    gone = next(entity for entity in published.entities if entity.legal_name == "PT Gone")
    assert (gone.first_listed, gone.last_listed, gone.on_newest_list, gone.left_after) == (
        date(2021, 1, 31), date(2021, 2, 28), False, date(2021, 2, 28),
    )
    company = next(company for company in published.companies if company.id == gone.company_id)
    assert (company.status, company.left_after) == ("left", date(2021, 2, 28))


def test_every_listing_is_published_as_listed() -> None:
    published = publication([LPBBTI], records(), KEYS)

    assert len(published.listings) == 5
    assert {listing.legal_name for listing in published.listings} == {"PT Fintech Bina Bangsa", "PT Gone"}


def test_a_register_without_records_is_still_published() -> None:
    (register,) = publication([LPBBTI], [], {}).registers

    assert (register.newest_edition, register.editions) == (None, 0)
