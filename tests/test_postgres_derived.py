"""The registry build against PostgreSQL: parse → resolve → validity → publish, from loaded bundles."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from amendment_world import build, load
from fakes import MemoryBlobStore

from metamorph_platform.adapters.postgres.migrate import migrate

pytestmark = pytest.mark.database


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


@pytest.fixture
def blobs() -> MemoryBlobStore:
    return MemoryBlobStore()


def rows(db, sql, *params):
    return db.execute(sql, params).fetchall()


def test_an_amendment_links_dates_and_expires_the_articles_it_changes(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path)

    report = build(db, blobs)

    assert report["parse"]["texts"] == 2
    # waiting: UU 21/2011, cited by the amending text and by each sample document's source record, isn't held
    assert report["resolve"] == {"linked": 3, "waiting": 3, "unidentified": 0, "links_dropped": 0}
    links = "SELECT type, from_address, to_document, to_address FROM published.link ORDER BY to_address NULLS FIRST"
    assert rows(db, links) == [
        ("amends", "pasal-i", "ojk:pojk:2018:35", None),
        ("partly_revokes", "pasal-i", "ojk:pojk:2018:35", "pasal-110"),
        ("amends", "pasal-i", "ojk:pojk:2018:35", "pasal-115"),
    ]  # fmt: skip
    assert rows(db, "SELECT effective_on, enacted_on FROM published.document WHERE id = 'ojk:pojk:2022:7'") == [
        (date(2022, 2, 27), date(2022, 2, 25))
    ]
    assert rows(
        db, "SELECT address, valid_to FROM published.provision WHERE document_id = 'ojk:pojk:2018:35' ORDER BY ordinal"
    ) == [
        ("pasal-110", date(2022, 2, 27)),
        ("pasal-115", date(2022, 2, 27)),
        ("pasal-115/ayat-1", date(2022, 2, 27)),
        ("pasal-115/ayat-2", date(2022, 2, 27)),
    ]
    assert rows(db, "SELECT body FROM published.provision WHERE address = 'pasal-115/ayat-2'") == [
        ("(2) Laporan disampaikan.\n",)
    ]
    assert rows(
        db, "SELECT address, status FROM published.status_event WHERE source = 'links' ORDER BY address NULLS FIRST"
    ) == [(None, "amended"), ("pasal-110", "revoked"), ("pasal-115", "amended")]


def test_building_again_changes_nothing(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path)
    build(db, blobs)

    again = build(db, blobs)

    assert again == {
        "parse": {"texts": 0, "provisions": 0, "citations": 0, "suspect": 0},
        "resolve": {"linked": 0, "waiting": 3, "unidentified": 0, "links_dropped": 0},
        "validity": {"status_changes": 3, "expiries": 2, "documents_changed": 0},
        "publish": {"added": 0, "updated": 0, "removed": 0, "held": 0},
    }
