"""Curated links between reports and the market layer: a register's or an industry's reports, by ID or by family."""

from __future__ import annotations

from datetime import date

from metamorph_platform.domain.market.links import industries, linked_reports
from metamorph_platform.domain.market.statistics import IndustryLink, PublishedDataset

PUBLISHED = ("ojk:lpksi:2024", "ojk:lpksi:2025", "ojk:roadmap:2023:lpbbti", "ojk:roadmap:2023:rp3si")


def test_a_family_names_every_published_edition_and_an_id_names_itself() -> None:
    assert linked_reports(("ojk:lpksi", "ojk:roadmap:2023:rp3si"), PUBLISHED) == (
        "ojk:lpksi:2025", "ojk:lpksi:2024", "ojk:roadmap:2023:rp3si",
    )


def test_a_link_to_a_report_not_published_names_nothing() -> None:
    assert linked_reports(("bi:keksi", "ojk:roadmap:2024:other"), PUBLISHED) == ()


def test_a_family_is_not_a_prefix_of_another_family() -> None:
    assert linked_reports(("ojk:lpk",), PUBLISHED) == ()


def dataset(id_: str, industry: str | None) -> PublishedDataset:
    return PublishedDataset(id_, "ojk:portal", industry, "", "metric", None, (), 1, date(2026, 1, 1),
                            date(2026, 8, 1), None, None, None)


def test_each_curated_industry_is_published_with_its_links_and_datasets() -> None:
    links = [IndustryLink("ojk:portal", "Bank Umum Syariah", None, ("id:uu:2008:21",), ("ojk:lpksi",)),
             IndustryLink("ojk:portal", "LPBBTI Syariah", "ojk:lpbbti", (), ())]
    datasets = [dataset("ojk:portal:bus_a", "Bank Umum Syariah"), dataset("ojk:portal:bus_b", "Bank Umum Syariah"),
                dataset("bi:seki:tabel1_1", None)]

    bus, lpbbti = industries(links, datasets, {"ojk:lpbbti": ("ojk:pojk:2024:40",)}, PUBLISHED)

    assert (bus.name, bus.governed_by, bus.reports, bus.datasets) == (
        "Bank Umum Syariah", ("id:uu:2008:21",), ("ojk:lpksi:2025", "ojk:lpksi:2024"),
        ("ojk:portal:bus_a", "ojk:portal:bus_b"),
    )
    assert (lpbbti.register, lpbbti.governed_by, lpbbti.datasets) == ("ojk:lpbbti", ("ojk:pojk:2024:40",), ())
