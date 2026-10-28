"""PublishMarket against in-memory ports: published_market is rebuilt whole from the records held."""

from __future__ import annotations

from market_platform_samples import answer_sha, edition_sha, licensed, series_record
from metamorph_market import LicenseKind

from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo
from metamorph_platform.domain.market.statistics import IndustryLink

LPBBTI = RegisterInfo("ojk:lpbbti", "ojk", "LPBBTI", ("ojk:pojk:2024:40",))
JAN, FEB = "2021-01-31", "2021-02-28"


class MemoryMarketSource:
    def __init__(self, records, series=()) -> None:  # noqa: ANN001
        self.records = records
        self.series = list(series)

    def register_infos(self) -> list[RegisterInfo]:
        return [LPBBTI]

    def industry_links(self) -> list[IndustryLink]:
        return [IndustryLink("ojk:portal", "Bank Umum Syariah", None, ("id:uu:2008:21",))]

    def current_records(self):  # noqa: ANN201
        return self.records

    def current_series(self):  # noqa: ANN201
        return self.series

    def storage_keys(self) -> dict[str, str]:
        return {edition_sha(JAN): "blobs/jan", answer_sha("2026"): "blobs/2026"}

    def citations(self) -> dict[str, str]:
        return {"ojk:portal": "Otoritas Jasa Keuangan, data.ojk.go.id"}


class MemoryPublishedMarket:
    def __init__(self) -> None:
        self.published: list[MarketPublication] = []

    def replace_all(self, publication: MarketPublication) -> None:
        self.published.append(publication)


def test_publishing_replaces_published_market_with_what_the_records_say() -> None:
    records = [
        licensed("S-1/NB.213/2019", JAN, legal_name="PT A", kind=LicenseKind.REGISTRATION),
        licensed("KEP-1/D.05/2021", FEB, legal_name="PT A"),
        licensed("KEP-2/D.05/2021", JAN, legal_name="PT B"),
    ]
    published = MemoryPublishedMarket()

    report = PublishMarket(MemoryMarketSource(records), published).run()

    (written,) = published.published
    assert (report.registers, report.companies, report.entities, report.editions) == (1, 2, 3, 2)
    assert written.editions[0].storage_key == "blobs/jan"


def test_series_are_published_beside_the_registers_in_the_same_rebuild() -> None:
    series = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0, "2026-02": 2.0}),
              series_record("BU_Syariah_PosisiKeuangan", "2", "Piutang", {"2026-01": 3.0})]
    published = MemoryPublishedMarket()

    report = PublishMarket(MemoryMarketSource([licensed("KEP-2/D.05/2021", JAN)], series), published).run()

    (written,) = published.published
    assert (report.registers, report.entities, report.datasets, report.series, report.observations) == (1, 1, 1, 2, 3)
    assert written.statistics.datasets[0].governed_by == ("id:uu:2008:21",)
    assert written.statistics.observations[0].storage_key == "blobs/2026"
    assert written.statistics.datasets[0].citation == "Otoritas Jasa Keuangan, data.ojk.go.id"
