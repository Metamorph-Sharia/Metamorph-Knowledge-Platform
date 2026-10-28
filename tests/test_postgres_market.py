"""The market data layer against a real PostgreSQL: load bundles, publish, read published_market back."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from market_platform_samples import (
    licensed,
    macro_series,
    series_record,
    write_market_bundle,
    write_report_bundle,
    write_series_bundle,
)
from metamorph_market import Bundle, LicenseKind

from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresReviewQueue
from metamorph_platform.adapters.postgres.market import PostgresMarket, PostgresPublishedMarket
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.ports import BundleAlreadyLoaded
from metamorph_platform.application.publish_market import PublishMarket

pytestmark = pytest.mark.database
JAN, FEB, MAR = "2021-01-31", "2021-02-28", "2021-03-31"


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


@pytest.fixture
def blobs():
    return MemoryBlobStore()  # the object store, shared by the loads and the publishes of one test


def load(db, directory, blobs=None):
    loader = LoadMarketBundle(
        PostgresIngestLedger(db), PostgresMarket(db), blobs or MemoryBlobStore(), PostgresReviewQueue(db)
    )
    return loader.run(Bundle(directory), uri=str(directory))


def publish(db, blobs=None):
    return PublishMarket(PostgresMarket(db), PostgresPublishedMarket(db), blobs or MemoryBlobStore()).run()


def snapshot():
    return [
        licensed("S-451/NB.213/2019", JAN, legal_name="PT Fintech Bina Bangsa", kind=LicenseKind.REGISTRATION),
        licensed("KEP-88/D.05/2021", FEB, MAR, legal_name="PT Fintech Bina Bangsa"),
        licensed("KEP-1/D.05/2020", JAN, FEB, legal_name="PT Gone"),
    ]


def test_a_bundle_loads_once_and_again_unchanged(tmp_path, db) -> None:
    first = load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    again = load(db, write_market_bundle(tmp_path / "b2", snapshot(), run_id="run-2"))

    assert (first.new, again.unchanged) == (3, 3)
    assert db.execute("SELECT count(*) FROM market.entity").fetchone() == (3,)
    assert db.execute("SELECT state, loaded FROM ingest.bundle WHERE id = %s", (first.bundle_id,)).fetchone() == (
        "loaded", 3,
    )
    with pytest.raises(BundleAlreadyLoaded):
        load(db, write_market_bundle(tmp_path / "b3", snapshot()))  # run-1 again


def test_a_record_dropped_from_the_snapshot_is_missing_and_left_out_of_published(tmp_path, db) -> None:
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    report = load(db, write_market_bundle(tmp_path / "b2", snapshot()[:2], run_id="run-2"))
    publish(db)

    assert report.missing == 1
    assert db.execute("SELECT count(*) FROM published_market.entity").fetchone() == (2,)


def test_publishing_joins_a_registration_and_its_license_into_one_company(tmp_path, db) -> None:
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))

    report = publish(db)

    assert (report.registers, report.editions, report.companies, report.entities) == (1, 3, 2, 3)
    company = db.execute(
        "SELECT id, status, first_listed::text FROM published_market.company WHERE legal_name = %s",
        ("PT Fintech Bina Bangsa",),
    ).fetchone()
    assert company == ("ojk:lpbbti:kep-88-d.05-2021", "licensed", JAN)
    kinds = db.execute(
        "SELECT kind FROM published_market.entity WHERE company_id = %s ORDER BY first_listed", (company[0],)
    ).fetchall()
    assert kinds == [("registration",), ("license",)]


def test_the_register_and_its_editions_are_published(tmp_path, db) -> None:
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    publish(db)

    register = db.execute(
        "SELECT newest_edition::text, editions, governed_by FROM published_market.register WHERE id = 'ojk:lpbbti'"
    ).fetchone()
    assert register == (MAR, 3, ["ojk:pojk:2024:40", "ojk:seojk:2025:19"])
    editions = db.execute(
        'SELECT edition::text, listed, joined, "left", storage_key IS NOT NULL FROM published_market.edition '
        "ORDER BY edition"
    ).fetchall()
    assert editions == [(JAN, 2, 2, 0, True), (FEB, 2, 1, 1, True), (MAR, 1, 0, 1, True)]


def test_publishing_again_replaces_rather_than_adds(tmp_path, db) -> None:
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    publish(db)
    publish(db)

    assert db.execute("SELECT count(*) FROM published_market.listing").fetchone() == (5,)
    assert db.execute("SELECT count(*) FROM published_market.company").fetchone() == (2,)


def test_health_checks_each_register_s_newest_published_edition(tmp_path, db) -> None:
    from metamorph_platform.adapters.postgres.health import PostgresHealth
    from metamorph_platform.application.check_health import CheckHealth
    from metamorph_platform.domain.health import Severity

    def register_check():  # noqa: ANN202
        checks = CheckHealth(PostgresHealth(db), cadence={}).run().checks
        return next(check for check in checks if check.name == "register ojk:lpbbti")

    assert register_check().detail == "no edition published yet"
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    publish(db)

    stale = register_check()
    assert stale.severity == Severity.WARNING
    assert stale.detail.startswith(f"newest edition {MAR},")


def series_snapshot():
    return [
        series_record("BU_Syariah_PosisiKeuangan", "110001010100", "003. 1. Kas dan Setara Kas",
                      {"2025-12": 10.0, "2026-01": 12.0}),
        series_record("LPBBTI_Syariah_PosisiKeuangan", "110001010100", "003. 1. Kas dan Setara Kas", {"2026-01": 1.0},
                      industry="Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah"),
    ]


def test_series_load_once_and_again_unchanged(tmp_path, db) -> None:
    first = load(db, write_series_bundle(tmp_path / "s1", series_snapshot()))
    again = load(db, write_series_bundle(tmp_path / "s2", series_snapshot(), run_id="run-2"))

    assert (first.new, again.unchanged) == (2, 2)
    assert db.execute("SELECT count(*), min(source) FROM market.series").fetchone() == (2, "ojk:portal")


def test_series_are_published_with_their_industry_s_links(tmp_path, db) -> None:
    load(db, write_market_bundle(tmp_path / "b1", snapshot()))
    load(db, write_series_bundle(tmp_path / "s1", series_snapshot()))

    report = publish(db)

    assert (report.registers, report.datasets, report.series, report.observations) == (1, 2, 2, 3)
    datasets = db.execute(
        "SELECT id, register, governed_by, first_period::text, last_period::text FROM published_market.dataset "
        "ORDER BY id"
    ).fetchall()
    assert datasets == [
        ("ojk:portal:bu_syariah_posisikeuangan", None, ["id:uu:2008:21", "ojk:pojk:2022:16", "ojk:pojk:2023:12"],
         "2025-12-01", "2026-01-01"),
        ("ojk:portal:lpbbti_syariah_posisikeuangan", "ojk:lpbbti", ["ojk:pojk:2024:40", "ojk:seojk:2025:19"],
         "2026-01-01", "2026-01-01"),
    ]
    observations = db.execute(
        "SELECT o.period::text, o.value, o.storage_key IS NOT NULL FROM published_market.observation o "
        "JOIN published_market.series s ON s.id = o.series_id WHERE s.dataset = 'ojk:portal:bu_syariah_posisikeuangan' "
        "ORDER BY o.period"
    ).fetchall()
    assert observations == [("2025-12-01", 10.0, True), ("2026-01-01", 12.0, True)]


def test_publishing_series_again_replaces_rather_than_adds(tmp_path, db) -> None:
    load(db, write_series_bundle(tmp_path / "s1", series_snapshot()))
    publish(db)
    publish(db)

    assert db.execute("SELECT count(*) FROM published_market.observation").fetchone() == (3,)


def test_series_dropped_from_the_snapshot_are_missing(tmp_path, db) -> None:
    load(db, write_series_bundle(tmp_path / "s1", series_snapshot()))
    report = load(db, write_series_bundle(tmp_path / "s2", series_snapshot()[:1], run_id="run-2"))
    publish(db)

    assert report.missing == 1
    assert db.execute("SELECT count(*) FROM published_market.series").fetchone() == (1,)


def test_health_checks_each_statistics_source_s_newest_period(tmp_path, db) -> None:
    from metamorph_platform.adapters.postgres.health import PostgresHealth
    from metamorph_platform.application.check_health import CheckHealth
    from metamorph_platform.domain.health import Severity

    def source_check():  # noqa: ANN202
        checks = CheckHealth(PostgresHealth(db), cadence={}).run().checks
        return next(check for check in checks if check.name == "statistics ojk:portal")

    assert source_check().detail == "no period published yet"
    load(db, write_series_bundle(tmp_path / "s1", series_snapshot()))
    publish(db)

    stale = source_check()
    assert stale.severity == Severity.WARNING
    assert stale.detail.startswith("newest period ended 2026-01-31,")


def test_a_macro_series_is_published_with_its_frequency_unit_marks_and_citation(tmp_path, db) -> None:
    load(db, write_series_bundle(tmp_path / "s1", [macro_series({"2026-Q1": 783624.1, "2026-Q2": 889052.3})]))
    publish(db)

    assert db.execute(
        "SELECT industry, citation FROM published_market.dataset WHERE id = 'bi:seki:tabel7_1'"
    ).fetchone() == (None, "Bank Indonesia, Statistik Ekonomi dan Keuangan Indonesia (SEKI)")
    assert db.execute("SELECT frequency, unit FROM published_market.series").fetchone() == ("quarterly", "Miliar Rp")
    assert db.execute(
        "SELECT period::text, provisional FROM published_market.observation ORDER BY period"
    ).fetchall() == [("2026-01-01", False), ("2026-04-01", True)]


def _pages(*counts: int) -> str:
    pages = [f"<!-- page {number} -->\n" + " ".join(["kata"] * count) for number, count in enumerate(counts, 1)]
    return "\n\n".join(pages)


def test_a_report_is_published_with_its_passages_and_its_pdf(tmp_path, db, blobs) -> None:
    load(db, write_report_bundle(tmp_path / "r1", {"ojk:lpksi:2025": _pages(300, 300)}), blobs)

    published = publish(db, blobs)

    assert (published.reports, published.passages, published.held_back) == (1, 2, 0)
    report = db.execute(
        "SELECT family, edition, citation, pages, passages, method, storage_key IS NOT NULL "
        "FROM published_market.report WHERE id = 'ojk:lpksi:2025'"
    ).fetchone()
    assert report == ("lpksi", "2025", "Otoritas Jasa Keuangan, Laporan Perkembangan Keuangan Syariah Indonesia 2025",
                      244, 2, "ocr", True)
    assert db.execute(
        "SELECT address, page_start, page_end, words FROM published_market.report_passage ORDER BY ordinal"
    ).fetchall() == [("p-1", 1, 1, 300), ("p-2", 2, 2, 300)]


def test_a_report_loads_again_unchanged_and_goes_when_dropped(tmp_path, db, blobs) -> None:
    both = {"ojk:lpksi:2024": _pages(300), "ojk:lpksi:2025": _pages(300)}
    load(db, write_report_bundle(tmp_path / "r1", both), blobs)

    again = load(db, write_report_bundle(tmp_path / "r2", {"ojk:lpksi:2025": both["ojk:lpksi:2025"]}, "run-2"), blobs)
    publish(db, blobs)

    assert (again.unchanged, again.missing) == (1, 1)
    assert db.execute("SELECT id FROM published_market.report").fetchall() == [("ojk:lpksi:2025",)]



def test_curated_links_name_the_published_reports_and_industries_are_published(tmp_path, db, blobs) -> None:
    load(db, write_series_bundle(tmp_path / "s1", [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas",
                                                                 {"2026-01": 1.0})]), blobs)
    load(db, write_report_bundle(tmp_path / "r1", {"ojk:lpksi:2025": _pages(300)}), blobs)

    publish(db, blobs)

    assert db.execute(
        "SELECT reports FROM published_market.dataset WHERE id = 'ojk:portal:bu_syariah_posisikeuangan'"
    ).fetchone() == (["ojk:lpksi:2025"],)
    assert db.execute(
        "SELECT governed_by, reports, datasets FROM published_market.industry "
        "WHERE source = 'ojk:portal' AND name = 'Bank Umum Syariah'"
    ).fetchone() == (["id:uu:2008:21", "ojk:pojk:2022:16", "ojk:pojk:2023:12"], ["ojk:lpksi:2025"],
                     ["ojk:portal:bu_syariah_posisikeuangan"])
    assert db.execute("SELECT count(*) FROM published_market.industry").fetchone() == (4,)
    assert db.execute("SELECT reports FROM published_market.register WHERE id = 'ojk:lpbbti'").fetchone() == ([],)
