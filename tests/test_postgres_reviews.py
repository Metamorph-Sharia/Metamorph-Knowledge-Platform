"""Settling review items against PostgreSQL: judged on today's texts, decided as the platform, audited."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import psycopg
import pytest
from contract_samples import PDF, build_document
from fakes import MemoryBlobStore
from metamorph_contract import Bundle, BundleWriter, NormalizedDocument

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks, PostgresParsedTexts
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.reviews import PLATFORM, PostgresOpenReviews
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.resolve_citations import ResolveCitations
from metamorph_platform.application.settle_reviews import SettleReviews

pytestmark = pytest.mark.database
DOCUMENT = "ojk:pojk:2018:35"

GAPPY = """\
PERATURAN OTORITAS JASA KEUANGAN
Mengingat : Keputusan Presiden Nomor 84/P Tahun 2009;
MEMUTUSKAN:
Pasal 1
Satu.
Pasal 3
Tiga.
"""
CORRECTED = GAPPY.replace("Keputusan Presiden Nomor 84/P Tahun 2009", "Undang-Undang Nomor 21 Tahun 2011").replace(
    "Pasal 3", "Pasal 2\nDua.\nPasal 3"
)


def regulation(text: str) -> NormalizedDocument:
    sample = build_document()
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(text.encode()).hexdigest(), paged=False)
    return replace(
        sample,
        source=replace(sample.source, source_id="regalert:target"),
        document=replace(sample.document, id=DOCUMENT, number="35", year=2018, citation="POJK 35/2018", aliases=()),
        texts=(text_ref,),
        provisions=(),
    )


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


@pytest.fixture
def blobs() -> MemoryBlobStore:
    return MemoryBlobStore()


def load_and_build(db, blobs, tmp_path, text: str, run: str) -> None:
    with BundleWriter(tmp_path / run, connector="ojk", connector_version="0.1.0", run_id=run) as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(text)
        bundle.add(regulation(text))
    reviews = PostgresReviewQueue(db)
    LoadBundle(PostgresIngestLedger(db), PostgresRegistry(db), blobs, reviews, PostgresOverrides(db)).run(
        Bundle(tmp_path / run), uri="x"
    )
    ParseTexts(PostgresParsedTexts(db), blobs, reviews).run()
    ResolveCitations(PostgresCitationLinks(db), reviews).run()


def open_kinds(db) -> list[str]:
    return [kind for (kind,) in db.execute("SELECT kind FROM curation.review_item WHERE state = 'open' ORDER BY kind")]


def test_items_whose_cause_remains_stay_open(db, blobs, tmp_path) -> None:
    load_and_build(db, blobs, tmp_path, GAPPY, "r1")

    report = SettleReviews(PostgresOpenReviews(db)).run()

    assert report.counts() == {"settled": {}, "needs_a_person": {"structure_suspect": 1, "unresolved_citation": 1}}
    assert open_kinds(db) == ["structure_suspect", "unresolved_citation"]


def test_items_a_corrected_text_answers_are_settled_as_the_platform_and_audited(db, blobs, tmp_path) -> None:
    load_and_build(db, blobs, tmp_path, GAPPY, "r1")
    load_and_build(db, blobs, tmp_path, CORRECTED, "r2")  # the source replaced its text

    report = SettleReviews(PostgresOpenReviews(db)).run()

    assert report.counts() == {"settled": {"structure_suspect": 1, "unresolved_citation": 1}, "needs_a_person": {}}
    assert open_kinds(db) == []
    decided = db.execute("SELECT kind, decided_by, note FROM curation.review_item ORDER BY kind").fetchall()
    assert decided == [
        ("structure_suspect", PLATFORM.username, "the text was replaced by a newer version"),
        ("unresolved_citation", PLATFORM.username, "the citation was linked, or the text no longer cites it"),
    ]
    audited = db.execute("SELECT author, action, reason FROM curation.audit_log ORDER BY id").fetchall()
    assert [(author, action) for author, action, _ in audited] == [(PLATFORM.username, "decide_review")] * 2
    assert SettleReviews(PostgresOpenReviews(db)).run().counts()["settled"] == {}
