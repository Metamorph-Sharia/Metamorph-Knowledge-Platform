"""Curating the market layer's links: checked first, written with its audit and relinked as one change, warned about."""

from __future__ import annotations

import pytest
from market_curation_samples import ANI, BUS, JournalledRelink, MemoryMarketCuration, MemoryPublishedNames

from metamorph_platform.application.curate_market import CurateMarket
from metamorph_platform.domain.curation import InvalidCorrection


@pytest.fixture
def journal() -> list[str]:
    return []


@pytest.fixture
def curate(journal) -> CurateMarket:
    return CurateMarket(MemoryMarketCuration(journal), MemoryPublishedNames(), JournalledRelink(journal))


def test_a_register_s_links_are_written_and_relinked_in_one_change_and_unpublished_names_warn(curate, journal) -> None:
    warnings = curate.set_register_links(ANI, "ojk:lpbbti", ["ojk:pojk:2024:40", "ojk:pojk:2026:9"], ["ojk:lpksi"],
                                         45, "  POJK 9/2026 amends the licensing rules ")

    assert journal == [
        "begin",
        "register ojk:lpbbti ('ojk:pojk:2024:40', 'ojk:pojk:2026:9') by ani: POJK 9/2026 amends the licensing rules",
        "relink",
        "commit",
    ]
    assert warnings == ("ojk:pojk:2026:9 is not published: it links nothing until it is",)


@pytest.mark.parametrize("change", [
    lambda curate: curate.set_register_links(ANI, "ojk:lpbbti", ["POJK 40/2024"], [], 45, "why"),
    lambda curate: curate.set_register_links(ANI, "ojk:lpbbti", [], [], 45, "   "),
    lambda curate: curate.set_industry(ANI, "ojk:portal", BUS, "ojk:lpbbti", ["id:uu:2008:21"], [], "why"),
    lambda curate: curate.set_source(ANI, "bi:seki", "", 90, "bi.go.id", "", "why"),
    lambda curate: curate.set_sector(ANI, "Sharia", "Syariah", "", [("ojk:portal", BUS)], "why"),
    lambda curate: curate.withdraw_sector(ANI, "sharia-banking", ""),
])
def test_what_cannot_apply_is_refused_before_anything_is_written(curate, journal, change) -> None:
    with pytest.raises(InvalidCorrection):
        change(curate)

    assert journal == []


def test_industries_sources_and_sectors_are_each_one_change_with_the_relink(curate, journal) -> None:
    curate.set_industry(ANI, "ojk:portal", BUS, None, ["id:uu:2008:21"], ["ojk:lpksi"], "RP3SI covers BUS")
    curate.withdraw_industry(ANI, "ojk:portal", BUS, "OJK renamed the industry")
    curate.set_source(ANI, "bi:seki", "Bank Indonesia, SEKI", 90, "https://www.bi.go.id/seki", "", "BI moved the page")
    curate.set_sector(ANI, "sharia-banking", "Perbankan Syariah", "Sharia banking", [("ojk:portal", BUS)], "one list")
    curate.withdraw_sector(ANI, "sharia-banking", "merged into sharia-finance")

    assert journal == [
        "begin", f"industry ojk:portal {BUS} None: RP3SI covers BUS", "relink", "commit",
        "begin", f"withdraw industry ojk:portal {BUS}: OJK renamed the industry", "relink", "commit",
        "begin", "source bi:seki https://www.bi.go.id/seki: BI moved the page", "relink", "commit",
        "begin", "sector sharia-banking 1: one list", "relink", "commit",
        "begin", "withdraw sector sharia-banking: merged into sharia-finance", "relink", "commit",
    ]
