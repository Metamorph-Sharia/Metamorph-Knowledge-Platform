"""PublishMarket against in-memory ports: published_market is rebuilt whole from the records held."""

from __future__ import annotations

from market_platform_samples import edition_sha, licensed
from metamorph_market import LicenseKind

from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.domain.market.publication import MarketPublication, RegisterInfo

LPBBTI = RegisterInfo("ojk:lpbbti", "ojk", "LPBBTI", ("ojk:pojk:2024:40",))
JAN, FEB = "2021-01-31", "2021-02-28"


class MemoryMarketSource:
    def __init__(self, records) -> None:  # noqa: ANN001
        self.records = records

    def register_infos(self) -> list[RegisterInfo]:
        return [LPBBTI]

    def current_records(self):  # noqa: ANN201
        return self.records

    def storage_keys(self) -> dict[str, str]:
        return {edition_sha(JAN): "blobs/jan"}


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
