"""Curation against PostgreSQL: overlays that survive reloads, conflicts, renames, links, and the audit log."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from metamorph_contract import Bundle
from platform_samples import document, unresolved, write_bundle

from metamorph_platform.adapters.postgres.curation import PostgresCurationActions, PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.curate import Curate
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.resolve_citations import ResolveCitations

pytestmark = pytest.mark.database
ANI = Curator("ani", "Ani Rahma")
BLOBS = MemoryBlobStore()
DOC = "ojk:pojk:2014:5"


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


class Platform:
    def __init__(self, db, tmp_path) -> None:
        self.db, self.tmp_path, self.runs = db, tmp_path, 0
        self.curate = Curate(PostgresCurationActions(db))

    def load(self, *documents) -> None:
        self.runs += 1
        directory = write_bundle(self.tmp_path / f"b{self.runs}", list(documents), run_id=f"run-{self.runs}")
        registry, reviews, overrides = (
            PostgresRegistry(self.db),
            PostgresReviewQueue(self.db),
            PostgresOverrides(self.db),
        )
        LoadBundle(PostgresIngestLedger(self.db), registry, BLOBS, reviews, overrides).run(Bundle(directory), uri="x")

    def publish(self) -> dict:
        publication = PostgresPublication(self.db)
        return Publish(publication, publication, BLOBS).run().counts()

    def one(self, query: str, *params):
        return self.db.execute(query, params).fetchone()


@pytest.fixture
def platform(db, tmp_path) -> Platform:
    return Platform(db, tmp_path)


def test_a_correction_is_published_and_survives_reloads(platform) -> None:
    platform.load(document())
    platform.curate.correct(ANI, DOC, "title", "Perizinan Usaha Lembaga Penjaminan", "Judul resmi di Lembaran Negara")

    platform.publish()
    platform.load(document(citation="POJK 5/2014"))  # the source changes another field
    platform.publish()

    assert platform.one("SELECT title, curated FROM published.document WHERE id = %s", DOC) == (
        "Perizinan Usaha Lembaga Penjaminan",
        True,
    )
    assert platform.one("SELECT count(*) FROM curation.conflict") == (0,)


def test_a_source_change_under_a_correction_raises_a_conflict_until_a_curator_decides(platform) -> None:
    platform.load(document())
    platform.curate.correct(ANI, DOC, "title", "Judul Kurator", "Typo di sumber")

    platform.load(document(title="Judul Baru dari Sumber"))

    (conflict_id, state) = platform.one("SELECT id, state FROM curation.conflict")
    assert state == "open"
    assert platform.one("SELECT count(*) FROM curation.review_item WHERE kind = 'conflict' AND state = 'open'") == (1,)

    platform.curate.resolve_conflict(ANI, conflict_id, "accept", "Sumber sudah benar")
    platform.publish()

    assert platform.one("SELECT title, curated FROM published.document WHERE id = %s", DOC) == (
        "Judul Baru dari Sumber",
        False,
    )
    assert platform.one("SELECT count(*) FROM curation.review_item WHERE kind = 'conflict' AND state = 'open'") == (0,)


def test_a_suppressed_document_leaves_published_and_a_restored_one_returns(platform) -> None:
    platform.load(document())
    platform.publish()

    platform.curate.suppress(ANI, DOC, "Duplikat dari dokumen lain")
    assert platform.publish()["removed"] == 1
    with pytest.raises(CurationRefused, match="already"):
        platform.curate.suppress(ANI, DOC, "lagi")

    platform.curate.restore(ANI, DOC, "Bukan duplikat")
    assert platform.publish()["added"] == 1


def test_an_assigned_id_renames_the_document_and_keeps_applying_on_reload(platform) -> None:
    platform.load(unresolved())
    old_id = unresolved().document.id
    platform.publish()

    platform.curate.assign_id(ANI, old_id, "ojk:pojk:2014:6", "Kop dokumen: 6/POJK.05/2014")
    platform.load(unresolved())  # the connector still can't identify it
    report = platform.publish()

    assert platform.one("SELECT count(*) FROM registry.document WHERE id = %s", old_id) == (0,)
    assert platform.one("SELECT family, number, year FROM registry.document WHERE id = 'ojk:pojk:2014:6'") == (
        "pojk",
        "6",
        2014,
    )
    assert platform.one("SELECT document_id FROM registry.document_source") == ("ojk:pojk:2014:6",)
    assert (report["added"], report["removed"]) == (1, 1)
    assert platform.one(
        "SELECT count(*) FROM curation.review_item WHERE kind = 'unresolved_id' AND state = 'open'"
    ) == (0,)


def test_an_assigned_id_already_in_use_is_refused(platform) -> None:
    platform.load(document(), unresolved())

    with pytest.raises(CurationRefused, match="suppress this one instead"):
        platform.curate.assign_id(ANI, unresolved().document.id, DOC, "x")


def test_a_hand_made_link_survives_the_citation_being_replaced(platform) -> None:
    law = document("regalert:uu-21-2011", id="id:uu:2011:21", issuer="id", family="uu", number="21", year=2011,
                   citation="UU 21/2011", aliases=())  # fmt: skip
    platform.load(document(), law)
    platform.db.execute("UPDATE registry.citation SET target_id = NULL")  # as if no connector had named it
    (citation_id,) = platform.one("SELECT id FROM registry.citation WHERE document_id = %s", DOC)

    platform.curate.link_citation(ANI, citation_id, "id:uu:2011:21", "Mengingat angka 1")
    platform.load(document(title="Judul diubah"), law)  # replaces the source's citations
    ResolveCitations(PostgresCitationLinks(platform.db), PostgresReviewQueue(platform.db)).run()

    assert platform.one("SELECT method FROM registry.link WHERE to_document = 'id:uu:2011:21'") == ("curated",)


def test_every_action_is_in_the_audit_log_with_its_author_and_reason(platform) -> None:
    platform.load(document())

    platform.curate.correct(ANI, DOC, "effective_on", "2014-04-08", "Tanggal berlaku")
    platform.curate.withdraw_correction(ANI, DOC, "effective_on", "Sumber sudah benar")

    rows = platform.db.execute("SELECT author, action, reason FROM curation.audit_log ORDER BY id").fetchall()
    assert rows == [("ani", "correct", "Tanggal berlaku"), ("ani", "withdraw_correction", "Sumber sudah benar")]
    assert platform.one("SELECT display_name FROM curation.curator") == ("Ani Rahma",)
