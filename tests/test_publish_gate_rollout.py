"""Migration 0010, which rolled the publish gate out once: what it withdraws must be what the gate would hold.

The database is migrated in full, set back to how the platform published before the gate, and then 0010's
SQL runs again: today's code can't build a database stopped at 0009, and the SQL is what ran.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import psycopg
import pytest
from contract_samples import PDF
from fakes import MemoryBlobStore
from metamorph_contract import Bundle, BundleWriter
from platform_samples import document, unresolved

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresParsedTexts
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import available, migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.publishing import hold_reasons_of, publication_of
from metamorph_platform.domain.structure import PARSER_VERSION

pytestmark = pytest.mark.database
ROLLOUT = 10
CLEAN = "PERATURAN OTORITAS JASA KEUANGAN\nMEMUTUSKAN:\nPasal 1\nSatu.\nPasal 2\nDua.\n"
GAPPY = CLEAN.replace("Pasal 2\nDua.", "Pasal 3\nTiga.")


def with_text(sample, text: str):
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(text.encode()).hexdigest(), paged=False)
    return replace(sample, texts=(text_ref,), provisions=(), citations=())


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


def roll_out(db) -> None:
    (rollout,) = (migration for migration in available() if migration.version == ROLLOUT)
    db.execute(rollout.sql)


def published_before_the_gate(db, tmp_path) -> None:
    """A clean, a gappy, a text-less and an unidentified document, all published as the platform did before
    the gate: whatever the registry held."""
    blobs = MemoryBlobStore()
    documents = [
        with_text(document("regalert:clean", id="ojk:pojk:2014:1", number="1"), CLEAN),
        with_text(document("regalert:gappy", id="ojk:pojk:2014:2", number="2"), GAPPY),
        replace(document("regalert:faq", id="ojk:pojk:2014:3", number="3"), texts=(), provisions=()),
        with_text(unresolved("regalert:unknown"), CLEAN),
    ]
    with BundleWriter(tmp_path / "b", connector="ojk", connector_version="0.1.0", run_id="r1") as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(CLEAN)
        bundle.put_text(GAPPY)
        for each in documents:
            bundle.add(each)
    reviews = PostgresReviewQueue(db)
    LoadBundle(PostgresIngestLedger(db), PostgresRegistry(db), blobs, reviews, PostgresOverrides(db)).run(
        Bundle(tmp_path / "b"), uri="x"
    )
    ParseTexts(PostgresParsedTexts(db), blobs).run()
    publication = PostgresPublication(db)
    for document_id in publication.documents_to_publish():
        publication.replace(publication_of(publication.snapshot(document_id), {}))
    reviews.ensure_open(ReviewKind.STRUCTURE_SUSPECT, {"document_id": "ojk:pojk:2014:2", "problems": ["x"]})
    reviews.ensure_open(ReviewKind.UNRESOLVED_ID, {"document_id": unresolved("regalert:unknown").document.id})
    reviews.ensure_open(ReviewKind.UNRESOLVED_CITATION, {"document_id": "ojk:pojk:2014:1", "target_text": "x"})


def ids(db, sql: str) -> set[str]:
    return {row[0] for row in db.execute(sql)}


def test_the_rollout_withdraws_exactly_what_the_gate_would_hold(db, tmp_path) -> None:
    published_before_the_gate(db, tmp_path)
    snapshot = PostgresPublication(db).snapshot
    published = ids(db, "SELECT id FROM published.document")
    would_hold = {d for d in published if hold_reasons_of(snapshot(d), PARSER_VERSION)}

    roll_out(db)

    assert ids(db, "SELECT id FROM published.document") == {"ojk:pojk:2014:1"}
    withdrawn = ids(db, "SELECT document_id FROM published.change_log WHERE change = 'removed'")
    assert withdrawn == would_hold == {"ojk:pojk:2014:2", "ojk:pojk:2014:3", unresolved("regalert:unknown").document.id}


def test_the_rollout_closes_the_review_items_the_gate_replaces_and_audits_them(db, tmp_path) -> None:
    published_before_the_gate(db, tmp_path)

    roll_out(db)

    items = db.execute("SELECT kind, state, decided_by, note FROM curation.review_item ORDER BY kind").fetchall()
    assert items == [
        ("structure_suspect", "resolved", "metamorph-platform", "replaced by the publish gate"),
        ("unresolved_citation", "open", None, None),
        ("unresolved_id", "resolved", "metamorph-platform", "replaced by the publish gate"),
    ]
    audited = db.execute("SELECT author, action, after FROM curation.audit_log").fetchall()
    assert audited == [("metamorph-platform", "decide_review", {"state": "resolved"})] * 2
