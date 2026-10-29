"""Curated links between reports and the market layer: a register's or an industry's reports, by ID or by family."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from market_platform_samples import macro_series, series_record

from metamorph_platform.domain.market.links import (
    DatasetKey,
    DatasetLinks,
    RegisterLinksRow,
    SectorDefinition,
    industries,
    linked_reports,
    relinked,
    with_links,
)
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo, publication
from metamorph_platform.domain.market.reports import PublishedReport, Reports
from metamorph_platform.domain.market.statistics import IndustryLink, PublishedDataset, statistics

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


LPBBTI = "Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah"
REGISTERS = [RegisterInfo("ojk:lpbbti", "ojk", "LPBBTI", ("ojk:pojk:2024:40",), ("ojk:roadmap:2023:lpbbti",))]
LINKS = [IndustryLink("ojk:portal", "Bank Umum Syariah", None, ("id:uu:2008:21",), ("ojk:lpksi",)),
         IndustryLink("ojk:portal", LPBBTI, "ojk:lpbbti", (), ("bi:keksi",))]
CITATIONS = {"ojk:portal": "Otoritas Jasa Keuangan, data.ojk.go.id", "bi:seki": "Bank Indonesia, SEKI"}
SECTORS = [SectorDefinition("sharia-finance", "Keuangan Syariah", "Sharia finance",
                            (("ojk:portal", "Bank Umum Syariah"), ("ojk:portal", LPBBTI)))]


def full_publish() -> MarketPublication:
    records = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0}),
               series_record("LPBBTI_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 2.0}, industry=LPBBTI),
               macro_series({"2026-Q1": 3.0})]
    found = statistics(LINKS, {r.id: r.governed_by for r in REGISTERS}, records, {}, CITATIONS)
    reports = Reports(tuple(report(id_) for id_ in PUBLISHED))
    return with_links(replace(publication(REGISTERS, [], {}), statistics=found, reports=reports), REGISTERS, LINKS,
                      SECTORS)


def test_relinking_gives_every_link_a_full_publish_gives() -> None:
    full = full_publish()
    keys = [DatasetKey(dataset.id, dataset.source, dataset.industry) for dataset in full.statistics.datasets]

    relink = relinked(keys, REGISTERS, LINKS, CITATIONS, PUBLISHED, SECTORS)

    assert relink.datasets == tuple(
        DatasetLinks(d.id, d.register, d.governed_by, d.reports, d.citation) for d in full.statistics.datasets)
    assert relink.registers == tuple(RegisterLinksRow(r.id, r.governed_by, r.reports) for r in full.registers)
    assert (relink.industries, relink.sectors) == (full.industries, full.sectors)


def test_a_sector_gathers_its_industries_registers_regulations_reports_and_datasets() -> None:
    (sector,) = full_publish().sectors

    assert sector.industries == ({"source": "ojk:portal", "name": "Bank Umum Syariah"},
                                 {"source": "ojk:portal", "name": LPBBTI})
    assert (sector.registers, sector.governed_by) == (("ojk:lpbbti",), ("id:uu:2008:21", "ojk:pojk:2024:40"))
    assert sector.reports == ("ojk:lpksi:2025", "ojk:lpksi:2024")
    assert sector.datasets == ("ojk:portal:bu_syariah_posisikeuangan", "ojk:portal:lpbbti_syariah_posisikeuangan")


def test_a_sector_s_industry_no_source_names_is_kept_and_adds_nothing() -> None:
    gone = SectorDefinition("sharia-finance", "Keuangan Syariah", "", (("ojk:portal", "Gone"),))

    (sector,) = relinked([], REGISTERS, LINKS, CITATIONS, PUBLISHED, [gone]).sectors

    assert (sector.industries, sector.datasets, sector.governed_by) == (({"source": "ojk:portal", "name": "Gone"},),
                                                                         (), ())


def report(id_: str) -> PublishedReport:
    return PublishedReport(id_, "ojk", id_.split(":")[1], "", id_, None, "id", None, id_, 1, 1, "text_layer", None)
