"""PublishMarket against in-memory ports: published_market is rebuilt whole from the records held."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from fakes import MemoryBlobReader
from market_platform_samples import (
    RELEASE_BODY,
    answer_sha,
    edition_sha,
    licensed,
    release_record,
    report_record,
    series_record,
)
from metamorph_market import LicenseKind

from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo
from metamorph_platform.domain.market.statistics import IndustryLink, Statistics

LPBBTI = RegisterInfo("ojk:lpbbti", "ojk", "LPBBTI", ("ojk:pojk:2024:40",), ("ojk:lpksi",))
JAN, FEB = "2021-01-31", "2021-02-28"


REPORT_TEXT = "<!-- page 1 -->\n" + " ".join(["kata"] * 300) + "\n\n<!-- page 2 -->\n" + " ".join(["kata"] * 300)


class MemoryMarketSource:
    def __init__(self, records, series=(), reports=(), releases=()) -> None:  # noqa: ANN001
        self.records = records
        self.series = list(series)
        self.reports = list(reports)
        self.releases = list(releases)

    def register_infos(self) -> list[RegisterInfo]:
        return [LPBBTI]

    def industry_links(self) -> list[IndustryLink]:
        return [IndustryLink("ojk:portal", "Bank Umum Syariah", None, ("id:uu:2008:21",), ("ojk:lpksi",))]

    def current_records(self):  # noqa: ANN201
        return self.records

    def current_series(self):  # noqa: ANN201
        return self.series

    def current_reports(self):  # noqa: ANN201
        return self.reports

    def current_releases(self):  # noqa: ANN201
        return self.releases

    def storage_keys(self) -> dict[str, str]:
        report = report_record(REPORT_TEXT)
        return {edition_sha(JAN): "blobs/jan", answer_sha("2026"): "blobs/2026",
                report.files[0].sha256: "blobs/lpksi.pdf", report.text.file: "blobs/lpksi.txt",
                hashlib.sha256(RELEASE_BODY).hexdigest(): "blobs/release.html"}

    def citations(self) -> dict[str, str]:
        return {"ojk:portal": "Otoritas Jasa Keuangan, data.ojk.go.id"}


class MemoryPublishedMarket:
    """Keeps what each publish writes: its statistics part by part, then the rest."""

    def __init__(self) -> None:
        self.parts: list[Statistics] = []
        self.published: list[MarketPublication] = []
        self.order: list[str] = []

    @contextmanager
    def replacing(self) -> Iterator[MemoryPublishedMarket]:
        yield self

    def add_statistics(self, part: Statistics) -> None:
        self.parts.append(part)
        self.order.append("statistics")

    def add(self, publication: MarketPublication) -> None:
        self.published.append(publication)
        self.order.append("the rest")


def test_publishing_replaces_published_market_with_what_the_records_say() -> None:
    records = [
        licensed("S-1/NB.213/2019", JAN, legal_name="PT A", kind=LicenseKind.REGISTRATION),
        licensed("KEP-1/D.05/2021", FEB, legal_name="PT A"),
        licensed("KEP-2/D.05/2021", JAN, legal_name="PT B"),
    ]
    published = MemoryPublishedMarket()

    report = PublishMarket(MemoryMarketSource(records), published, MemoryBlobReader({})).run()

    (written,) = published.published
    assert (report.registers, report.companies, report.entities, report.editions) == (1, 2, 3, 2)
    assert written.editions[0].storage_key == "blobs/jan"


def test_series_are_published_beside_the_registers_in_the_same_rebuild() -> None:
    series = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0, "2026-02": 2.0}),
              series_record("BU_Syariah_PosisiKeuangan", "2", "Piutang", {"2026-01": 3.0})]
    published = MemoryPublishedMarket()

    source = MemoryMarketSource([licensed("KEP-2/D.05/2021", JAN)], series)
    report = PublishMarket(source, published, MemoryBlobReader({})).run()

    (part,) = published.parts
    assert (report.registers, report.entities, report.datasets, report.series, report.observations) == (1, 1, 1, 2, 3)
    assert part.datasets[0].governed_by == ("id:uu:2008:21",)
    assert part.observations[0].storage_key == "blobs/2026"
    assert part.datasets[0].citation == "Otoritas Jasa Keuangan, data.ojk.go.id"
    assert published.order == ["statistics", "the rest"]


def test_series_are_written_in_parts_of_whole_datasets_so_a_publish_never_holds_them_all() -> None:
    series = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0, "2026-02": 2.0}),
              series_record("BU_Syariah_PosisiKeuangan", "2", "Piutang", {"2026-01": 3.0}),
              series_record("BPRS_PosisiKeuangan", "1", "Kas", {"2026-01": 4.0})]
    published = MemoryPublishedMarket()

    report = PublishMarket(MemoryMarketSource([], series), published, MemoryBlobReader({}), series_per_part=1).run()

    assert [[dataset.id for dataset in part.datasets] for part in published.parts] == [
        ["ojk:portal:bu_syariah_posisikeuangan"], ["ojk:portal:bprs_posisikeuangan"]]
    assert [len(part.series) for part in published.parts] == [2, 1]
    assert (report.datasets, report.series, report.observations) == (2, 3, 4)
    (written,) = published.published
    assert [dataset.id for dataset in written.statistics.datasets] == [  # for the industries, written last
        "ojk:portal:bu_syariah_posisikeuangan", "ojk:portal:bprs_posisikeuangan"]


def test_reports_are_published_with_their_passages_in_the_same_rebuild() -> None:
    published, texts = MemoryPublishedMarket(), MemoryBlobReader({"blobs/lpksi.txt": REPORT_TEXT.encode()})
    source = MemoryMarketSource([licensed("KEP-2/D.05/2021", JAN)], reports=[report_record(REPORT_TEXT)])

    report = PublishMarket(source, published, texts).run()

    (written,) = published.published
    assert (report.registers, report.reports, report.passages, report.held_back) == (1, 1, 2, 0)
    assert written.reports.reports[0].storage_key == "blobs/lpksi.pdf"
    assert [passage.page_start for passage in written.reports.passages] == [1, 2]
    assert texts.reads == ["blobs/lpksi.txt"]


def test_a_report_whose_text_is_not_kept_is_held_back() -> None:
    published = MemoryPublishedMarket()
    source = MemoryMarketSource([], reports=[report_record("<!-- page 1 -->\nnot stored")])

    report = PublishMarket(source, published, MemoryBlobReader({})).run()

    assert (report.reports, report.held_back) == (0, 1)


def test_registers_datasets_and_industries_name_their_published_reports() -> None:
    published, texts = MemoryPublishedMarket(), MemoryBlobReader({"blobs/lpksi.txt": REPORT_TEXT.encode()})
    series = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0})]
    source = MemoryMarketSource([licensed("KEP-2/D.05/2021", JAN)], series, reports=[report_record(REPORT_TEXT)])

    PublishMarket(source, published, texts).run()

    (written,) = published.published
    assert written.registers[0].reports == ("ojk:lpksi:2025",)
    assert published.parts[0].datasets[0].reports == ("ojk:lpksi:2025",)
    (industry,) = written.industries
    assert (industry.name, industry.reports, industry.datasets) == (
        "Bank Umum Syariah", ("ojk:lpksi:2025",), ("ojk:portal:bu_syariah_posisikeuangan",),
    )



def test_releases_are_published_with_their_passages_and_mentions_in_the_same_rebuild() -> None:
    published, texts = MemoryPublishedMarket(), MemoryBlobReader({"blobs/lpksi.txt": REPORT_TEXT.encode()})
    release = release_record("OJK mencabut izin usaha PT Tri Digi Fin berdasarkan POJK Nomor 10 Tahun 2022.")
    source = MemoryMarketSource([licensed("KEP-2/D.05/2021", JAN, legal_name="PT Tri Digi Fin")],
                                reports=[report_record(REPORT_TEXT)], releases=[release])

    report = PublishMarket(source, published, texts).run()

    (written,) = published.published
    assert (report.reports, report.releases, report.release_passages, report.mentions) == (1, 1, 1, 2)
    assert written.releases.releases[0].storage_key == "blobs/release.html"
    assert [(m.kind, m.target_kind, m.target) for m in written.mentions] == [
        ("release", "regulation", "ojk:pojk:2022:10"),
        ("release", "company", written.companies[0].id),
    ]


def test_a_release_without_words_is_held_back_beside_the_reports() -> None:
    published = MemoryPublishedMarket()

    report = PublishMarket(MemoryMarketSource([], releases=[release_record("")]), published, MemoryBlobReader({})).run()

    assert (report.releases, report.held_back) == (0, 1)
