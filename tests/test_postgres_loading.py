"""Loading and publishing against a real PostgreSQL (blobs stay in memory; S3 has its own test)."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from metamorph_contract import Bundle
from platform_samples import document, unresolved, write_bundle

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresParsedTexts
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import BundleAlreadyLoaded
from metamorph_platform.application.publish import Publish

pytestmark = pytest.mark.database
BLOBS = MemoryBlobStore()  # content-addressed, so every test may share it


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


def load(db, directory):
    loader = LoadBundle(
        PostgresIngestLedger(db), PostgresRegistry(db), BLOBS, PostgresReviewQueue(db), PostgresOverrides(db)
    )
    return loader.run(Bundle(directory), uri=str(directory))


def publish(db, everything=False):
    """Parse, then publish, as a build does: the publish gate only lets parsed texts through."""
    ParseTexts(PostgresParsedTexts(db), BLOBS).run()
    publication = PostgresPublication(db)
    return Publish(publication, publication, BLOBS, holds=publication).run(everything=everything).counts()


def one(db, sql, *params):
    return db.execute(sql, params).fetchone()


def test_a_bundle_becomes_registry_rows_and_then_published_rows(db, tmp_path) -> None:
    report = load(db, write_bundle(tmp_path / "b1", [document()]))

    assert (report.new, report.unchanged) == (1, 0)
    assert one(db, "SELECT title, status, citation FROM registry.document") == (
        "Perizinan Usaha dan Kelembagaan Lembaga Penjaminan",
        "in_force",
        "POJK 5/POJK.05/2014",
    )
    assert one(db, "SELECT count(*) FROM registry.citation WHERE target_id = 'id:uu:2011:21'") == (1,)
    assert one(db, "SELECT count(*) FROM registry.provision WHERE origin = 'source'") == (1,)
    assert one(db, "SELECT state, loaded FROM ingest.bundle") == ("loaded", 1)

    assert publish(db) == {"added": 1, "updated": 0, "removed": 0, "held": 0}
    assert one(db, "SELECT id, aliases FROM published.document") == (
        "ojk:pojk:2014:5",
        ["5/POJK.05/2014", "POJK 5/2014", "POJK 5/POJK.05/2014"],
    )
    assert one(db, "SELECT count(*) FROM published.text") == (1,)
    assert one(db, "SELECT change FROM published.change_log") == ("added",)


def test_reloading_and_republishing_an_unchanged_snapshot_is_a_no_op(db, tmp_path) -> None:
    load(db, write_bundle(tmp_path / "b1", [document()]))
    publish(db)

    report = load(db, write_bundle(tmp_path / "b2", [document()], run_id="run-2"))

    assert (report.new, report.changed, report.unchanged) == (0, 0, 1)
    assert publish(db) == {"added": 0, "updated": 0, "removed": 0, "held": 0}
    assert one(db, "SELECT count(*) FROM published.change_log") == (1,)


def test_a_changed_document_is_republished(db, tmp_path) -> None:
    load(db, write_bundle(tmp_path / "b1", [document()]))
    publish(db)

    load(db, write_bundle(tmp_path / "b2", [document(title="JUDUL BARU")], run_id="run-2"))

    assert publish(db) == {"added": 0, "updated": 1, "removed": 0, "held": 0}
    assert one(db, "SELECT title FROM published.document") == ("JUDUL BARU",)
    assert one(db, "SELECT count(*) FROM ingest.event WHERE kind = 'document_changed'") == (1,)


def test_a_curator_override_wins_and_a_suppression_unpublishes(db, tmp_path) -> None:
    load(db, write_bundle(tmp_path / "b1", [document()]))
    publish(db)
    db.execute("INSERT INTO curation.curator (username, display_name) VALUES ('rina', 'Rina')")
    db.execute(
        "INSERT INTO curation.override (document_id, field, value, reason, author) "
        "VALUES ('ojk:pojk:2014:5', 'status', '\"revoked\"', 'replaced by POJK 2/2026', 'rina')"
    )

    assert publish(db) == {"added": 0, "updated": 1, "removed": 0, "held": 0}
    assert one(db, "SELECT status, curated FROM published.document") == ("revoked", True)

    db.execute(
        "INSERT INTO curation.suppression (document_id, reason, author) VALUES ('ojk:pojk:2014:5', 'test', 'rina')"
    )
    assert publish(db) == {"added": 0, "updated": 0, "removed": 1, "held": 0}
    assert one(db, "SELECT change FROM published.change_log ORDER BY id DESC LIMIT 1") == ("removed",)


def test_an_unresolved_document_is_held_rather_than_queued(db, tmp_path) -> None:
    load(db, write_bundle(tmp_path / "b1", [unresolved()]))

    assert publish(db)["held"] == 1
    assert one(db, "SELECT count(*) FROM curation.review_item WHERE state = 'open'") == (0,)
    assert one(db, "SELECT reasons -> 0 ->> 'check' FROM registry.hold") == ("identity",)


def test_a_broken_line_is_quarantined_with_its_problems(db, tmp_path) -> None:
    report = load(db, write_bundle(tmp_path / "b1", [document()], extra_lines=["{not json"]))

    assert report.quarantined == 1
    assert one(db, "SELECT line, payload FROM ingest.quarantine") == (2, "{not json")
    assert one(db, "SELECT quarantined FROM ingest.bundle") == (1,)


def test_a_document_gone_from_the_snapshot_is_marked_but_still_published(db, tmp_path) -> None:
    load(db, write_bundle(tmp_path / "b1", [document("regalert:a"), document("regalert:b", id="ojk:pojk:2014:6")]))
    publish(db)

    report = load(db, write_bundle(tmp_path / "b2", [document("regalert:a")], run_id="run-2"))

    assert report.missing == 1
    assert one(db, "SELECT count(*) FROM registry.document_source WHERE missing_since IS NOT NULL") == (1,)
    assert one(db, "SELECT count(*) FROM published.document") == (2,)


def test_a_run_loads_once_but_a_failed_run_may_retry(db, tmp_path) -> None:
    directory = write_bundle(tmp_path / "b1", [document()])
    load(db, directory)
    with pytest.raises(BundleAlreadyLoaded):
        load(db, directory)

    db.execute("UPDATE ingest.bundle SET state = 'failed'")
    assert load(db, directory).unchanged == 1


def test_health_is_assessed_from_loads_and_recorded(db, tmp_path) -> None:
    from metamorph_platform.adapters.postgres.health import PostgresHealth
    from metamorph_platform.application.check_health import CheckHealth
    from metamorph_platform.domain.health import Severity

    load(db, write_bundle(tmp_path / "b1", [document()]))

    health = CheckHealth(PostgresHealth(db)).run()

    by_name = {check.name: check.severity for check in health.checks}
    assert by_name["ojk"] == Severity.OK
    assert by_name["bpk"] == Severity.CRITICAL  # never loaded in this database
    assert one(db, "SELECT status FROM ingest.health_snapshot") == ("critical",)
