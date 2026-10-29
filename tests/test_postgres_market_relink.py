"""Publishing what the curated links decide against a real PostgreSQL: sectors, a links-only publish, one lock."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from market_platform_samples import series_record, write_series_bundle
from metamorph_market import Bundle

from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresReviewQueue
from metamorph_platform.adapters.postgres.market import PUBLISH_LOCK, PostgresMarket, PostgresPublishedMarket
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.application.relink_market import RelinkMarket
from metamorph_platform.domain.market.links import SectorDefinition

pytestmark = pytest.mark.database
BUS = "Bank Umum Syariah"
LPBBTI = "Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah"
LINKED = {
    "register": "SELECT id, governed_by, reports FROM published_market.register ORDER BY id",
    "dataset": "SELECT id, register, governed_by, reports, citation FROM published_market.dataset ORDER BY id",
    "industry": "SELECT source, name, register, governed_by, reports, datasets FROM published_market.industry "
                "ORDER BY source, name",
    "sector": "SELECT id, name, name_en, industries, registers, governed_by, reports, datasets "
              "FROM published_market.sector ORDER BY id",
}


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


def loaded(db, tmp_path) -> None:
    records = [series_record("BU_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 1.0}),
               series_record("LPBBTI_Syariah_PosisiKeuangan", "1", "Kas", {"2026-01": 2.0}, industry=LPBBTI)]
    directory = write_series_bundle(tmp_path / "s1", records)
    loader = LoadMarketBundle(PostgresIngestLedger(db), PostgresMarket(db), MemoryBlobStore(), PostgresReviewQueue(db))
    loader.run(Bundle(directory), uri=str(directory))


def publish(db) -> None:
    PublishMarket(PostgresMarket(db), PostgresPublishedMarket(db), MemoryBlobStore()).run()


def relink(db) -> None:
    RelinkMarket(PostgresMarket(db), PostgresPublishedMarket(db)).run()


def linked(db) -> dict[str, list[tuple]]:
    return {name: db.execute(query).fetchall() for name, query in LINKED.items()}


def sector(db, definition: SectorDefinition) -> None:
    db.execute("INSERT INTO market.sector (id, name, name_en) VALUES (%s, %s, %s)",
               (definition.id, definition.name, definition.name_en))
    for ordinal, (source, name) in enumerate(definition.industries):
        db.execute("INSERT INTO market.sector_industry (sector, source, name, ordinal) VALUES (%s, %s, %s, %s)",
                   (definition.id, source, name, ordinal))


def test_a_sector_is_published_with_what_its_industries_link(tmp_path, db) -> None:
    loaded(db, tmp_path)
    sector(db, SectorDefinition("sharia-finance", "Keuangan Syariah", "Sharia finance",
                                (("ojk:portal", BUS), ("ojk:portal", LPBBTI))))

    publish(db)

    assert db.execute(
        "SELECT industries, registers, governed_by, datasets FROM published_market.sector"
    ).fetchone() == (
        [{"source": "ojk:portal", "name": BUS}, {"source": "ojk:portal", "name": LPBBTI}],
        ["ojk:lpbbti"],
        ["id:uu:2008:21", "ojk:pojk:2022:16", "ojk:pojk:2023:12", "ojk:pojk:2024:40", "ojk:seojk:2025:19"],
        ["ojk:portal:bu_syariah_posisikeuangan", "ojk:portal:lpbbti_syariah_posisikeuangan"],
    )


def test_relinking_after_a_link_changes_gives_what_a_full_publish_gives(tmp_path, db) -> None:
    loaded(db, tmp_path)
    publish(db)
    db.execute("UPDATE market.industry SET governed_by = '{ojk:pojk:2024:7}' WHERE name = %s", (BUS,))
    db.execute("UPDATE market.register SET governed_by = '{ojk:pojk:2024:40}' WHERE id = 'ojk:lpbbti'")
    db.execute("UPDATE market.statistics_source SET citation = 'OJK' WHERE id = 'ojk:portal'")
    sector(db, SectorDefinition("sharia-banking", "Perbankan Syariah", "", (("ojk:portal", BUS),)))

    relink(db)
    after_relink = linked(db)
    publish(db)

    assert after_relink == linked(db)
    assert after_relink["dataset"][0][2:] == (["ojk:pojk:2024:7"], [], "OJK")
    assert after_relink["sector"][0][5] == ["ojk:pojk:2024:7"]


@pytest.mark.parametrize("run", [publish, relink])
def test_a_full_publish_and_a_relink_take_one_lock_so_neither_overwrites_the_other(tmp_path, db, database_url,
                                                                                    run) -> None:
    loaded(db, tmp_path)
    with psycopg.connect(database_url) as other, other.transaction():
        other.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLISH_LOCK,))
        db.execute("SET lock_timeout = '200ms'")

        with pytest.raises(psycopg.errors.LockNotAvailable):
            run(db)
