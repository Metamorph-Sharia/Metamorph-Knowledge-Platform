"""Curating the market layer's links against a real PostgreSQL: written, audited and published as one change."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from market_platform_samples import series_record, write_series_bundle
from metamorph_market import Bundle

from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresReviewQueue
from metamorph_platform.adapters.postgres.market import PostgresMarket, PostgresPublishedMarket
from metamorph_platform.adapters.postgres.market_curation import PostgresMarketCuration
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.application.curate_market import CurateMarket
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.application.relink_market import RelinkMarket

pytestmark = pytest.mark.database
ANI = Curator("ani", "Ani Rahma")
BUS = "Bank Umum Syariah"
BUS_DATASET = "ojk:portal:bu_syariah_posisikeuangan"


@pytest.fixture
def db(database_url, tmp_path):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        directory = write_series_bundle(tmp_path / "s1", [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas",
                                                                        {"2026-01": 1.0})])
        LoadMarketBundle(PostgresIngestLedger(connection), PostgresMarket(connection), MemoryBlobStore(),
                         PostgresReviewQueue(connection)).run(Bundle(directory), uri=str(directory))
        PublishMarket(PostgresMarket(connection), PostgresPublishedMarket(connection), MemoryBlobStore()).run()
        yield connection


@pytest.fixture
def curate(db) -> CurateMarket:
    curation = PostgresMarketCuration(db)
    return CurateMarket(curation, curation, RelinkMarket(PostgresMarket(db), PostgresPublishedMarket(db)))


def audited(db) -> list[tuple]:
    return db.execute("SELECT author, action, target, before, after, reason FROM curation.audit_log ORDER BY id"
                      ).fetchall()


def test_a_register_s_links_are_written_audited_and_published_at_once(db, curate) -> None:
    warnings = curate.set_register_links(ANI, "ojk:lpbbti", ["ojk:pojk:2024:40"], ["ojk:lpksi"], 30, "SEOJK 19 is "
                                         "implementing, not governing")

    assert db.execute("SELECT governed_by, reports, fresh_days FROM market.register").fetchone() == (
        ["ojk:pojk:2024:40"], ["ojk:lpksi"], 30)
    assert db.execute("SELECT governed_by FROM published_market.register").fetchone() == (["ojk:pojk:2024:40"],)
    ((author, action, target, before, after, reason),) = audited(db)
    assert (author, action, target, reason) == ("ani", "market.set_register_links", {"register": "ojk:lpbbti"},
                                                "SEOJK 19 is implementing, not governing")
    assert before["governed_by"] == ["ojk:pojk:2024:40", "ojk:seojk:2025:19"]
    assert after == {"governed_by": ["ojk:pojk:2024:40"], "reports": ["ojk:lpksi"], "fresh_days": 30}
    assert warnings == ("ojk:pojk:2024:40 is not published: it links nothing until it is",
                        "ojk:lpksi names no published report: it links nothing until one is")


def test_a_change_that_names_nothing_held_is_refused_and_leaves_nothing_behind(db, curate) -> None:
    with pytest.raises(CurationRefused, match="no register ojk:gone"):
        curate.set_register_links(ANI, "ojk:gone", [], [], 30, "why")
    with pytest.raises(CurationRefused, match="no register ojk:gone"):
        curate.set_industry(ANI, "ojk:portal", BUS, "ojk:gone", [], [], "why")
    with pytest.raises(CurationRefused, match="no statistics source ojk:gone"):
        curate.set_source(ANI, "ojk:gone", "", 30, "", "", "why")
    with pytest.raises(CurationRefused, match="no industry Gone of ojk:portal"):
        curate.withdraw_industry(ANI, "ojk:portal", "Gone", "why")
    with pytest.raises(CurationRefused, match="no statistics source ojk:gone"):
        curate.set_sector(ANI, "sharia-banking", "Perbankan Syariah", "", [("ojk:gone", BUS)], "why")
    with pytest.raises(CurationRefused, match="no sector sharia-banking"):
        curate.withdraw_sector(ANI, "sharia-banking", "why")

    assert audited(db) == []


def test_an_industry_s_links_reach_its_datasets_at_once_and_go_when_it_is_withdrawn(db, curate) -> None:
    curate.set_industry(ANI, "ojk:portal", BUS, None, ["ojk:pojk:2024:7"], [], "POJK 7/2024 replaced the others")
    linked = db.execute("SELECT governed_by FROM published_market.dataset WHERE id = %s", (BUS_DATASET,)).fetchone()

    curate.withdraw_industry(ANI, "ojk:portal", BUS, "OJK renamed the industry")

    assert linked == (["ojk:pojk:2024:7"],)
    assert db.execute("SELECT governed_by FROM published_market.dataset WHERE id = %s", (BUS_DATASET,)).fetchone() == (
        [],)
    assert db.execute("SELECT count(*) FROM published_market.industry WHERE name = %s", (BUS,)).fetchone() == (0,)
    assert [row[1] for row in audited(db)] == ["market.set_industry", "market.withdraw_industry"]


def test_a_source_s_citation_and_download_page_are_kept_and_its_datasets_cited_anew(db, curate) -> None:
    curate.set_source(ANI, "ojk:portal", "OJK, data.ojk.go.id", 120, "https://data.ojk.go.id", "", "a shorter citation")

    assert db.execute("SELECT citation, download_page FROM market.statistics_source WHERE id = 'ojk:portal'"
                      ).fetchone() == ("OJK, data.ojk.go.id", "https://data.ojk.go.id")
    assert db.execute("SELECT citation FROM published_market.dataset WHERE id = %s", (BUS_DATASET,)).fetchone() == (
        "OJK, data.ojk.go.id",)


def test_a_sector_is_kept_in_its_curator_s_order_published_and_withdrawn(db, curate) -> None:
    bprs = "Bank Perekonomian Rakyat (BPR) Syariah"
    curate.set_sector(ANI, "sharia-banking", "Perbankan Syariah", "Sharia banking",
                      [("ojk:portal", bprs), ("ojk:portal", BUS)], "one list for industry_context")
    published = db.execute("SELECT industries, datasets FROM published_market.sector").fetchone()
    curate.set_sector(ANI, "sharia-banking", "Perbankan Syariah", "Sharia banking", [("ojk:portal", BUS)], "BUS only")

    assert published == ([{"source": "ojk:portal", "name": bprs}, {"source": "ojk:portal", "name": BUS}],
                         [BUS_DATASET])
    assert db.execute("SELECT name FROM market.sector_industry ORDER BY ordinal").fetchall() == [(BUS,)]
    curate.withdraw_sector(ANI, "sharia-banking", "merged")
    assert db.execute("SELECT count(*) FROM published_market.sector").fetchone() == (0,)
    assert [row[1] for row in audited(db)] == ["market.set_sector", "market.set_sector", "market.withdraw_sector"]
