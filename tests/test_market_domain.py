"""The market layer's rules: a license's standing on its register, companies, and what each edition changed."""

from datetime import date

from metamorph_market import BusinessType, LicenseKind

from metamorph_platform.domain.market import (
    CompanyStatus,
    HeldLicense,
    companies,
    edition_changes,
    review_notes,
    standing,
)

JAN, FEB, MAR = date(2021, 1, 31), date(2021, 2, 28), date(2021, 3, 31)


def held(
    license_id: str,
    *editions: date,
    names: tuple[str, ...] = ("PT Lender",),
    kind: LicenseKind = LicenseKind.LICENSE,
    business_type: BusinessType = BusinessType.CONVENTIONAL,
    register: str = "ojk:lpbbti",
) -> HeldLicense:
    return HeldLicense(license_id, register, kind, business_type, editions, names)


def test_a_license_on_the_newest_list_is_listed() -> None:
    found = standing(held("a", JAN, FEB, MAR), newest=MAR)

    assert (found.first_listed, found.last_listed, found.on_newest_list, found.left_after) == (JAN, MAR, True, None)


def test_a_license_missing_from_the_newest_list_left_after_its_last_edition() -> None:
    found = standing(held("a", JAN, FEB), newest=MAR)

    assert not found.on_newest_list
    assert found.left_after == FEB


def test_a_registration_and_a_license_listed_under_one_legal_name_are_one_company() -> None:
    registration = held("ojk:lpbbti:s-451", JAN, names=("PT Fintech Bina Bangsa",), kind=LicenseKind.REGISTRATION)
    license_ = held("ojk:lpbbti:kep-88", FEB, MAR, names=("PT  FINTECH Bina-Bangsa",))
    other = held("ojk:lpbbti:kep-1", JAN, MAR, names=("PT Other",))

    joined = companies([license_, registration, other], newest=MAR)

    fintech = next(company for company in joined if len(company.members) == 2)
    assert fintech.id == "ojk:lpbbti:kep-88"  # its newest license
    assert fintech.members == ("ojk:lpbbti:s-451", "ojk:lpbbti:kep-88")  # oldest first
    assert fintech.status is CompanyStatus.LICENSED
    assert len(joined) == 2


def test_a_name_shared_through_a_rename_joins_too() -> None:
    first = held("r", JAN, names=("PT Old Name",), kind=LicenseKind.REGISTRATION)
    renamed = held("l", FEB, MAR, names=("PT Old Name", "PT New Name"))

    (company,) = companies([first, renamed], newest=MAR)

    assert company.members == ("r", "l")


def test_names_on_different_registers_never_join() -> None:
    lender = held("a", JAN, names=("PT Same",))
    insurer = held("b", JAN, names=("PT Same",), register="ojk:insurance")

    assert len(companies([lender, insurer], newest=JAN)) == 2


def test_a_company_s_status_comes_from_its_newest_record() -> None:
    registered = companies([held("r", JAN, MAR, kind=LicenseKind.REGISTRATION)], newest=MAR)[0]
    gone = companies([held("g", JAN)], newest=MAR)[0]

    assert registered.status is CompanyStatus.REGISTERED
    assert (gone.status, gone.left_after) == (CompanyStatus.LEFT, JAN)


def test_each_edition_s_change_adds_up() -> None:
    licenses = [held("a", JAN, FEB, MAR), held("b", JAN), held("c", FEB, MAR), held("d", MAR)]

    jan, feb, mar = edition_changes(licenses)

    assert (jan.edition, jan.listed, jan.joined, jan.left) == (JAN, 2, 2, 0)
    assert (feb.listed, feb.joined, feb.left) == (2, 1, 1)
    assert (mar.listed, mar.joined, mar.left) == (3, 1, 0)


def test_an_unknown_business_type_or_kind_is_noted_never_held_back() -> None:
    unclear = held("x", JAN, kind=LicenseKind.UNKNOWN, business_type=BusinessType.UNKNOWN)

    assert review_notes(unclear) == ("business type unknown", "license kind unknown")
    assert review_notes(held("a", JAN)) == ()
