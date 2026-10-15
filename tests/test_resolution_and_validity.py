"""Citations become links when their target is held; amending and revoking links set validity."""

from __future__ import annotations

from datetime import date

from metamorph_platform.domain.resolution import Resolution, identifiable, resolve
from metamorph_platform.domain.validity import (
    DatedLink,
    ProvisionExpiry,
    StatusChange,
    provision_expiries,
    status_changes,
)

KNOWN = {"id:uu:2011:21", "ojk:pojk:2014:31"}
ALIASES = {"uu otoritas jasa keuangan": "id:uu:2011:21"}


def test_the_connector_s_own_target_id_resolves_first():
    assert resolve("ojk:pojk:2014:31", "POJK on Sharia Financing", known=KNOWN, aliases=ALIASES) == Resolution(
        "ojk:pojk:2014:31", "exact_id"
    )


def test_the_id_its_text_names_resolves_next():
    resolution = resolve(None, "Undang-Undang Nomor 21 Tahun 2011", known=KNOWN, aliases=ALIASES)

    assert resolution == Resolution("id:uu:2011:21", "exact_id")


def test_an_alias_resolves_last():
    assert resolve(None, "UU  Otoritas Jasa Keuangan", known=KNOWN, aliases=ALIASES) == Resolution(
        "id:uu:2011:21", "alias"
    )


def test_a_target_not_held_stays_open_until_it_is():
    assert resolve("id:uu:1998:10", "Undang-Undang Nomor 10 Tahun 1998", known=KNOWN, aliases=ALIASES) is None
    assert resolve("id:uu:1998:10", "…", known=KNOWN | {"id:uu:1998:10"}, aliases=ALIASES) is not None


def test_a_citation_naming_no_id_at_all_needs_a_person():
    assert identifiable("id:uu:1998:10", "…")
    assert identifiable(None, "Undang-Undang Nomor 10 Tahun 1998")
    assert not identifiable(None, "Peraturan pelaksanaan dari Undang-Undang ini")


DAY = date(2022, 3, 1)


def link(type_: str, to_address: str | None = None, effective_on: date | None = DAY, link_id: int = 1) -> DatedLink:
    return DatedLink(link_id, type_, "ojk:pojk:2022:7", "ojk:pojk:2018:35", to_address, effective_on)


def test_a_revocation_ends_the_target_document_from_the_revoking_one_s_effective_date():
    assert status_changes([link("revokes")]) == [StatusChange("ojk:pojk:2018:35", None, "revoked", DAY, 1)]
    assert status_changes([link("supersedes")])[0].status == "revoked"


def test_an_amendment_marks_the_document_amended_and_each_article_it_changes():
    changes = status_changes([link("amends"), link("amends", "pasal-115", link_id=2)])

    assert changes == [
        StatusChange("ojk:pojk:2018:35", None, "amended", DAY, 1),
        StatusChange("ojk:pojk:2018:35", "pasal-115", "amended", DAY, 2),
    ]


def test_a_partial_revocation_revokes_the_articles_it_names():
    changes = status_changes([link("partly_revokes", "pasal-30")])

    assert changes == [StatusChange("ojk:pojk:2018:35", "pasal-30", "revoked", DAY, 1)]


def test_a_changed_or_revoked_article_expires_its_old_wording_once_dated():
    links = [link("amends", "pasal-115"), link("partly_revokes", "pasal-30"), link("amends", "pasal-9", None)]

    assert provision_expiries(links) == [
        ProvisionExpiry("ojk:pojk:2018:35", "pasal-115", DAY),
        ProvisionExpiry("ojk:pojk:2018:35", "pasal-30", DAY),
    ]


def test_the_earliest_change_to_an_article_ends_its_original_wording():
    later = link("amends", "pasal-115", date(2024, 1, 1), link_id=2)

    assert provision_expiries([later, link("amends", "pasal-115")]) == [
        ProvisionExpiry("ojk:pojk:2018:35", "pasal-115", DAY)
    ]


def test_links_that_change_nothing_are_ignored():
    assert status_changes([link("legal_basis"), link("adopts_fatwa")]) == []
