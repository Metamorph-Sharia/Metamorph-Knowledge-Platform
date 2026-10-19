"""The publish gate against PostgreSQL: what a snapshot tells it, and what it keeps published."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import psycopg
import pytest
from contract_samples import PDF, build_document
from fakes import MemoryBlobStore
from metamorph_contract import Bundle, BundleWriter, NormalizedDocument

from metamorph_platform.adapters.postgres.curation import PostgresCurationActions, PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresParsedTexts
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.adapters.postgres.views import PostgresCurationViews
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.application.publish import Publish
from metamorph_platform.domain.gate import Approval, Check, HoldReason, MainText
from metamorph_platform.domain.structure import PARSER_VERSION

pytestmark = pytest.mark.database
DOCUMENT = "ojk:pojk:2018:35"

CLEAN = """\
PERATURAN OTORITAS JASA KEUANGAN
MEMUTUSKAN:
Pasal 1
Satu.
Pasal 2
Dua.
"""
GAPPY = CLEAN.replace("Pasal 2\nDua.\n", "Pasal 3\nTiga.\n")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def regulation(text: str) -> NormalizedDocument:
    sample = build_document()
    return replace(
        sample,
        source=replace(sample.source, source_id="regalert:target"),
        document=replace(sample.document, id=DOCUMENT, number="35", year=2018, citation="POJK 35/2018", aliases=()),
        texts=(replace(sample.texts[0], sha256=sha(text), paged=False),),
        provisions=(),
        citations=(),
    )


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


@pytest.fixture
def blobs() -> MemoryBlobStore:
    return MemoryBlobStore()


def load_and_parse(db, blobs, tmp_path, text: str, run: str) -> None:
    with BundleWriter(tmp_path / run, connector="ojk", connector_version="0.1.0", run_id=run) as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(text)
        bundle.add(regulation(text))
    reviews = PostgresReviewQueue(db)
    LoadBundle(PostgresIngestLedger(db), PostgresRegistry(db), blobs, reviews, PostgresOverrides(db)).run(
        Bundle(tmp_path / run), uri="x"
    )
    ParseTexts(PostgresParsedTexts(db), blobs).run()


def test_a_snapshot_carries_each_main_text_as_parsed_and_the_active_approvals(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    db.execute("INSERT INTO curation.curator (username, display_name) VALUES ('ana', 'Ana')")
    db.execute(
        "INSERT INTO curation.approval (document_id, text_sha256, problems, reason, author) "
        "VALUES (%s, %s, '[\"Pasal 2 missing\"]', 'deleted by an amendment', 'ana')",
        (DOCUMENT, sha(GAPPY)),
    )

    snapshot = PostgresPublication(db).snapshot(DOCUMENT)

    parsed = MainText(sha(GAPPY), parsed_sha256=sha(GAPPY), parsed_with=PARSER_VERSION, problems=("Pasal 2 missing",))
    assert snapshot.main_texts == (parsed,)
    assert snapshot.approvals == (Approval(sha(GAPPY), ("Pasal 2 missing",)),)


def publish(db, blobs) -> dict[str, int]:
    publication = PostgresPublication(db)
    return Publish(publication, publication, blobs, holds=publication).run().counts()


def published_rows(db) -> list[tuple]:
    return db.execute(
        "SELECT d.title, t.sha256, p.address, p.body FROM published.document d "
        "JOIN published.text t ON t.document_id = d.id JOIN published.provision p ON p.document_id = d.id "
        "WHERE d.id = %s ORDER BY p.ordinal",
        (DOCUMENT,),
    ).fetchall()


def holds(db) -> list[tuple]:
    return db.execute("SELECT document_id, reasons FROM registry.hold ORDER BY document_id").fetchall()


def test_a_document_that_starts_failing_keeps_its_last_good_version(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, CLEAN, "r1")
    assert publish(db, blobs)["added"] == 1
    good = published_rows(db)
    logged = db.execute("SELECT count(*) FROM published.change_log").fetchone()

    load_and_parse(db, blobs, tmp_path, GAPPY, "r2")  # the source replaced its text with a damaged one

    assert publish(db, blobs)["held"] == 1
    assert published_rows(db) == good
    assert db.execute("SELECT count(*) FROM published.change_log").fetchone() == logged
    assert holds(db) == [(DOCUMENT, [{"check": "structure", "detail": "Pasal 2 missing"}])]


def test_a_document_never_published_stays_out_until_it_passes(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    assert publish(db, blobs)["held"] == 1
    assert published_rows(db) == []

    load_and_parse(db, blobs, tmp_path, CLEAN, "r2")

    assert publish(db, blobs)["added"] == 1
    assert holds(db) == []


ANA = Curator("ana", "Ana")


def test_a_curator_approves_the_problems_of_a_held_text_and_it_is_published(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    actions = PostgresCurationActions(db)

    actions.approve(ANA, DOCUMENT, sha(GAPPY), "Pasal 2 was deleted by an amendment")

    assert publish(db, blobs)["added"] == 1
    approved = db.execute("SELECT problems, author FROM curation.approval WHERE active").fetchall()
    assert approved == [(["Pasal 2 missing"], "ana")]
    audited = db.execute("SELECT action, target, after FROM curation.audit_log").fetchall()
    assert audited == [
        ("approve", {"document_id": DOCUMENT, "text_sha256": sha(GAPPY)}, {"problems": ["Pasal 2 missing"]})
    ]


def test_a_withdrawn_approval_holds_the_document_again_at_its_last_good_version(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    actions = PostgresCurationActions(db)
    actions.approve(ANA, DOCUMENT, sha(GAPPY), "deleted by an amendment")
    publish(db, blobs)
    good = published_rows(db)

    actions.withdraw_approval(ANA, DOCUMENT, sha(GAPPY), "Pasal 2 is in the PDF after all")

    assert publish(db, blobs)["held"] == 1
    assert published_rows(db) == good
    with pytest.raises(CurationRefused, match="no approval"):
        actions.withdraw_approval(ANA, DOCUMENT, sha(GAPPY), "again")


def test_an_approval_lapses_when_the_texts_problems_change(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    PostgresCurationActions(db).approve(ANA, DOCUMENT, sha(GAPPY), "deleted by an amendment")
    db.execute(  # a newer parser reads the same text differently
        "UPDATE registry.text_version SET structure_problems = '[\"Pasal 4 missing\"]'"
    )
    db.execute("UPDATE registry.document SET updated_at = now()")

    assert publish(db, blobs)["held"] == 1


def test_only_a_current_main_text_with_problems_can_be_approved(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, CLEAN, "r1")
    actions = PostgresCurationActions(db)

    with pytest.raises(CurationRefused, match="no structure problems"):
        actions.approve(ANA, DOCUMENT, sha(CLEAN), "x")
    with pytest.raises(CurationRefused, match="isn't a current main text"):
        actions.approve(ANA, DOCUMENT, sha(GAPPY), "x")


def test_the_held_list_and_the_document_page_show_why_and_what_is_still_published(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, CLEAN, "r1")
    publish(db, blobs)
    load_and_parse(db, blobs, tmp_path, GAPPY, "r2")
    publish(db, blobs)
    views = PostgresCurationViews(db)

    held = views.held_page(None, 1)
    (row,) = held.rows
    assert (row.document_id, row.reasons) == (DOCUMENT, (HoldReason(Check.STRUCTURE, "Pasal 2 missing"),))
    assert row.published_at is not None
    assert dict(held.counts) == {"identity": 0, "text": 0, "parsed": 0, "structure": 1}
    assert views.held_page("text", 1).rows == ()
    assert (views.dashboard().held, views.dashboard().held_published) == (1, 1)

    page = views.document(DOCUMENT)
    assert page.hold == (HoldReason(Check.STRUCTURE, "Pasal 2 missing"),) and page.published_at is not None


def test_the_document_page_shows_an_approval_only_while_it_covers_the_texts_problems(db, blobs, tmp_path) -> None:
    load_and_parse(db, blobs, tmp_path, GAPPY, "r1")
    PostgresCurationActions(db).approve(ANA, DOCUMENT, sha(GAPPY), "deleted by an amendment")
    views = PostgresCurationViews(db)

    (text,) = views.document(DOCUMENT).texts
    assert (text.approval.reason, text.approval.author) == ("deleted by an amendment", "ana")

    db.execute("UPDATE registry.text_version SET structure_problems = '[\"Pasal 4 missing\"]'")
    (text,) = views.document(DOCUMENT).texts
    assert text.approval is None
