"""What a curator may set in the market layer's curated links: checked by form, warned about when unpublished."""

from __future__ import annotations

import pytest

from metamorph_platform.domain.curation import InvalidCorrection
from metamorph_platform.domain.market.curation import (
    RegisterLinks,
    SourceSettings,
    industry_link,
    link_warnings,
    register_links,
    sector_definition,
    source_settings,
)
from metamorph_platform.domain.market.links import SectorDefinition
from metamorph_platform.domain.market.statistics import IndustryLink

BUS = "Bank Umum Syariah"


def test_a_register_s_links_are_canonical_regulations_and_reports_or_families_kept_once_in_order() -> None:
    links = register_links([" ojk:pojk:2024:40 ", "ojk:seojk:2025:19", "ojk:pojk:2024:40"],
                           ["ojk:roadmap:2023:lpbbti", "ojk:lpksi"], 45)

    assert links == RegisterLinks(("ojk:pojk:2024:40", "ojk:seojk:2025:19"), ("ojk:roadmap:2023:lpbbti", "ojk:lpksi"),
                                  45)


@pytest.mark.parametrize(("governed_by", "reports", "fresh_days", "message"), [
    (["POJK 40 Tahun 2024"], [], 45, "POJK 40 Tahun 2024 is not a document ID, such as ojk:pojk:2024:40"),
    ([], ["LPKSI 2025"], 45, "LPKSI 2025 is not a report ID or family, such as ojk:lpksi:2025 or ojk:lpksi"),
    ([], [], 0, "fresh_days must be between 1 and 3650"),
])
def test_a_link_that_is_not_an_id_is_refused_with_what_is_expected(governed_by, reports, fresh_days, message) -> None:
    with pytest.raises(InvalidCorrection, match=message):
        register_links(governed_by, reports, fresh_days)


def test_an_industry_links_a_register_or_regulations_of_its_own_never_both() -> None:
    assert industry_link("ojk:portal", f" {BUS} ", None, ["id:uu:2008:21"], ["ojk:lpksi"]) == IndustryLink(
        "ojk:portal", BUS, None, ("id:uu:2008:21",), ("ojk:lpksi",))
    assert industry_link("ojk:portal", "LPBBTI Syariah", "ojk:lpbbti", [], []).register == "ojk:lpbbti"

    with pytest.raises(InvalidCorrection, match="a register's regulations, or its own: not both"):
        industry_link("ojk:portal", BUS, "ojk:lpbbti", ["id:uu:2008:21"], [])
    with pytest.raises(InvalidCorrection, match="name the industry as its source does"):
        industry_link("ojk:portal", "  ", None, [], [])


def test_a_source_s_settings_name_its_download_page_by_a_web_address() -> None:
    settings = source_settings(" Bank Indonesia, SEKI ", 90, "https://www.bi.go.id/id/statistik/seki/Default.aspx",
                               " SEKI_{MONTH}_{YEAR}.zip ")

    assert settings == SourceSettings("Bank Indonesia, SEKI", 90, "https://www.bi.go.id/id/statistik/seki/Default.aspx",
                                      "SEKI_{MONTH}_{YEAR}.zip")
    assert source_settings("", 120, "", "") == SourceSettings(None, 120, None, None)
    with pytest.raises(InvalidCorrection, match="the download page must be a web address"):
        source_settings("", 90, "bi.go.id/seki", "")


def test_a_sector_gathers_industries_across_sources_under_one_id() -> None:
    sector = sector_definition("sharia-banking", " Perbankan Syariah ", "Sharia banking",
                               [("ojk:portal", BUS), ("ojk:portal", "Bank Perekonomian Rakyat (BPR) Syariah"),
                                ("ojk:portal", BUS)])

    assert sector == SectorDefinition("sharia-banking", "Perbankan Syariah", "Sharia banking",
                                      (("ojk:portal", BUS), ("ojk:portal", "Bank Perekonomian Rakyat (BPR) Syariah")))
    with pytest.raises(InvalidCorrection, match="a sector's ID is lowercase words joined by hyphens"):
        sector_definition("Sharia Banking", "Perbankan Syariah", "", [("ojk:portal", BUS)])
    with pytest.raises(InvalidCorrection, match="a sector gathers at least one industry"):
        sector_definition("sharia-banking", "Perbankan Syariah", "", [])


def test_links_to_what_is_not_published_warn_and_are_kept() -> None:
    warnings = link_warnings(["ojk:pojk:2024:40", "ojk:pojk:2026:9"], ["ojk:lpksi", "ojk:roadmap:2030:x"],
                             published_documents={"ojk:pojk:2024:40"}, published_reports=["ojk:lpksi:2025"])

    assert warnings == (
        "ojk:pojk:2026:9 is not published: it links nothing until it is",
        "ojk:roadmap:2030:x names no published report: it links nothing until one is",
    )
