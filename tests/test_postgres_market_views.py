"""The console's market pages' queries against PostgreSQL, on a published market layer."""

from __future__ import annotations

import json
from datetime import date

import psycopg
import pytest
from fakes import MemoryBlobStore
from market_platform_samples import (
    RELEASE_BODY,
    REPORT_PDF,
    licensed,
    release_record,
    report_record,
    series_record,
    write_market_bundle,
    write_series_bundle,
)
from metamorph_market import Bundle, BundleWriter, BusinessType, LicenseKind

from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresReviewQueue
from metamorph_platform.adapters.postgres.market import PostgresMarket, PostgresPublishedMarket
from metamorph_platform.adapters.postgres.market_views import PostgresMarketViews
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.views import PostgresCurationViews
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.market_views import (
    CompanyFilters,
    DatasetFilters,
    IndustryName,
    NamedTarget,
)
from metamorph_platform.application.publish_market import PublishMarket

pytestmark = pytest.mark.database
JAN, FEB = "2021-01-31", "2021-02-28"
BUS = "Bank Umum Syariah"
BUS_DATASET = "ojk:portal:bu_syariah_posisikeuangan"
RELEASE = "ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital"
RELEASE_TEXT = ("SP 188/DKPU/OJK/X/2026\n\nSIARAN PERS\n\nJakarta, 8 Oktober 2026. OJK mencabut izin usaha "
                "PT FINTECH BINA BANGSA sesuai Peraturan Otoritas Jasa Keuangan Nomor 40 Tahun 2024.")
REPORT_TEXT = ("<!-- page 1 -->\n" + " ".join(["kata"] * 300) + "\n\n<!-- page 2 -->\n"
               "Peraturan Otoritas Jasa Keuangan Nomor 40 Tahun 2024 " + " ".join(["kata"] * 300))


@pytest.fixture
def connection(database_url, tmp_path):
    blobs = MemoryBlobStore()
    with psycopg.connect(database_url, autocommit=True) as db:
        migrate(db)

        def load(directory):
            loader = LoadMarketBundle(PostgresIngestLedger(db), PostgresMarket(db), blobs, PostgresReviewQueue(db))
            return loader.run(Bundle(directory), uri=str(directory))

        load(write_market_bundle(tmp_path / "b1", [
            licensed("S-451/NB.213/2019", JAN, legal_name="PT Fintech Bina Bangsa", kind=LicenseKind.REGISTRATION,
                     business_type=BusinessType.SHARIA),
            licensed("KEP-88/D.05/2021", FEB, legal_name="PT Fintech Bina Bangsa", business_type=BusinessType.SHARIA),
            licensed("KEP-1/D.05/2020", JAN, legal_name="PT Gone"),
        ]))
        load(write_series_bundle(tmp_path / "s1", [
            series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0, "2026-02": 2.0}),
            series_record("BU_Syariah_PosisiKeuangan", "2", "Piutang", {"2026-01": 3.0}),
            series_record("BPRS_PosisiKeuangan", "1", "Kas", {"2026-01": 4.0},
                          industry="Bank Perekonomian Rakyat (BPR) Syariah"),
        ]))
        load(reports_and_releases(tmp_path / "r1"))
        PublishMarket(PostgresMarket(db), PostgresPublishedMarket(db), blobs).run()
        yield db


def reports_and_releases(directory):
    """What the reports connector sends: its reports and releases in one bundle, and here a line no contract reads."""
    with BundleWriter(directory, connector="reports", connector_version="0.2.0", run_id="run-1") as bundle:
        bundle.put_blob(REPORT_PDF)
        bundle.put_blob(REPORT_TEXT.encode())
        bundle.add(report_record(REPORT_TEXT))
        bundle.put_blob(RELEASE_BODY)
        bundle.add(release_record(RELEASE_TEXT))
    with (directory / "records.jsonl").open("a") as lines:
        lines.write(json.dumps({"kind": "release", "release": {"id": "broken"}}) + "\n")
    return directory


@pytest.fixture
def views(connection) -> PostgresMarketViews:
    return PostgresMarketViews(connection)


def test_the_overview_counts_the_market_layer_and_its_open_reviews(views) -> None:
    overview = views.overview()

    counts = overview.counts
    assert (counts.companies, counts.entities, counts.datasets, counts.series, counts.observations) == (2, 3, 2, 3, 4)
    assert (counts.reports, counts.releases, counts.sectors) == (1, 1, 0)
    assert counts.mentions >= 2
    assert overview.open_reviews == 1  # the broken line of the releases' bundle
    assert {bundle.connector for bundle in overview.recent_bundles} == {"ojk-register", "ojk-stats", "reports"}


def test_the_sources_page_holds_the_curated_links_and_what_they_reach(views) -> None:
    sources = views.sources()

    (register,) = sources.registers
    assert (register.id, register.governed_by, register.companies) == (
        "ojk:lpbbti", ("ojk:pojk:2024:40", "ojk:seojk:2025:19"), 2)
    seki = next(source for source in sources.sources if source.id == "bi:seki")
    assert seki.download_page == "https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Default.aspx"
    portal = next(source for source in sources.sources if source.id == "ojk:portal")
    assert (portal.datasets, portal.series, portal.newest_period) == (2, 3, date(2026, 2, 1))
    bus = next(industry for industry in sources.industries if industry.name == BUS)
    assert (bus.governed_by, bus.datasets) == (("id:uu:2008:21", "ojk:pojk:2022:16", "ojk:pojk:2023:12"), 1)
    assert sources.named_industries == (IndustryName("ojk:portal", "Bank Perekonomian Rakyat (BPR) Syariah"),
                                        IndustryName("ojk:portal", BUS))


def test_companies_are_found_by_name_and_filtered_and_one_shows_its_licences_and_what_names_it(views) -> None:
    found = views.companies("bina", CompanyFilters(), 1)
    sharia = views.companies("", CompanyFilters(business_type="sharia"), 1)
    left = views.companies("", CompanyFilters(status="left"), 1)

    assert [row.legal_name for row in found.rows] == ["PT Fintech Bina Bangsa"]
    assert [row.legal_name for row in sharia.rows] == ["PT Fintech Bina Bangsa"]
    assert [row.legal_name for row in left.rows] == ["PT Gone"]
    company = views.company(found.rows[0].id)
    assert {entity.kind for entity in company.entities} == {"license", "registration"}
    assert [(m.kind, m.document, m.published_on) for m in company.mentions] == [
        ("release", RELEASE, date(2026, 10, 8))]
    assert views.company("nobody") is None


def test_datasets_are_found_and_one_lists_its_series_and_a_series_its_figures(views) -> None:
    found = views.datasets("posisikeuangan", DatasetFilters(industry=BUS), 1)

    assert [row.id for row in found.rows] == [BUS_DATASET]
    dataset = views.dataset(BUS_DATASET, 1)
    assert (dataset.series_total, dataset.governed_by, dataset.citation is not None) == (
        2, ("id:uu:2008:21", "ojk:pojk:2022:16", "ojk:pojk:2023:12"), True)
    series = views.series(dataset.series[0].id)
    assert [(o.period, o.value) for o in series.observations] == [(date(2026, 1, 1), 1.0), (date(2026, 2, 1), 2.0)]
    assert (views.dataset("gone", 1), views.series("gone")) == (None, None)


def test_a_report_and_a_release_are_read_by_their_passages_with_what_each_names(views) -> None:
    (report_row,) = views.reports()
    report = views.report(report_row.id, 1)
    releases = views.releases("cabut", date(2026, 1, 1), None, 1)
    release = views.release(RELEASE)

    assert [(p.page_start, p.page_end) for p in report.passages] == [(1, 1), (2, 2)]
    assert NamedTarget("regulation", "ojk:pojk:2024:40") in report.passages[1].names
    assert [row.id for row in releases.rows] == [RELEASE]
    assert views.releases("", date(2027, 1, 1), None, 1).rows == ()
    assert release.citation == "Siaran Pers OJK SP 188/DKPU/OJK/X/2026, 8 Oktober 2026"
    assert {target.kind for target in release.passages[0].names} == {"regulation", "company"}


def test_a_quarantined_line_is_named_by_its_bundle_s_connector(connection) -> None:
    (row,) = PostgresCurationViews(connection).review_page("quarantine", 1).rows

    assert row.summary.startswith("Bundle ")
    assert "(reports), line 3: " in row.summary
