"""The registry build against PostgreSQL: parse → resolve → validity → publish, from loaded bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date

import psycopg
import pytest
from contract_samples import PDF, build_document
from fakes import MemoryBlobStore
from metamorph_contract import Bundle, BundleWriter, NormalizedDocument

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks, PostgresParsedTexts, PostgresValidity
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.compute_validity import ComputeValidity
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.resolve_citations import ResolveCitations
from metamorph_platform.domain.structure import grammar_for, parse

pytestmark = pytest.mark.database

TARGET_TEXT = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 35/POJK.05/2018
Pasal 110
Dihapus nanti.
Pasal 115
(1) Perusahaan wajib melapor.
(2) Laporan disampaikan.
"""
AMENDING_TEXT = """\
PERATURAN OTORITAS JASA KEUANGAN
NOMOR 7/POJK.05/2022
Mengingat : Undang-Undang Nomor 21 Tahun 2011 tentang Otoritas Jasa Keuangan;
MEMUTUSKAN:
Pasal I
Beberapa ketentuan dalam Peraturan Otoritas Jasa Keuangan Nomor 35/POJK.05/2018 diubah sebagai berikut:
1. Ketentuan Pasal 115 diubah sehingga berbunyi sebagai berikut:
Pasal 115
(1) Perusahaan wajib melapor setiap bulan.
2. Pasal 110 dihapus.
Pasal II
Peraturan Otoritas Jasa Keuangan ini mulai berlaku pada tanggal diundangkan.
Ditetapkan di Jakarta
pada tanggal 25 Februari 2022
Diundangkan di Jakarta
pada tanggal 27 Februari 2022
"""


def regulation(source_id: str, document_id: str, text: str) -> NormalizedDocument:
    sample = build_document()
    number, year = document_id.split(":")[3], int(document_id.split(":")[2])
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(text.encode()).hexdigest(), paged=False)
    return replace(
        sample,
        source=replace(sample.source, source_id=source_id),
        document=replace(sample.document, id=document_id, number=number, year=year, citation=f"POJK {number}/{year}",
                         aliases=(), dates=replace(sample.document.dates, effective=None)),
        texts=(text_ref,),
        provisions=(),
    )  # fmt: skip


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


@pytest.fixture
def blobs() -> MemoryBlobStore:
    return MemoryBlobStore()


def load(db, blobs, tmp_path) -> None:
    with BundleWriter(tmp_path / "bundle", connector="ojk", connector_version="0.1.0", run_id="r1") as bundle:
        bundle.put_blob(PDF)
        for source_id, document_id, text in (
            ("regalert:target", "ojk:pojk:2018:35", TARGET_TEXT),
            ("regalert:amending", "ojk:pojk:2022:7", AMENDING_TEXT),
        ):
            bundle.put_text(text)
            bundle.add(regulation(source_id, document_id, text))
    reviews = PostgresReviewQueue(db)
    LoadBundle(PostgresIngestLedger(db), PostgresRegistry(db), blobs, reviews, PostgresOverrides(db)).run(
        Bundle(tmp_path / "bundle"), uri="x"
    )
    approve_as_is(db, "ojk:pojk:2018:35", TARGET_TEXT)


def approve_as_is(db, document_id: str, text: str) -> None:
    """TARGET_TEXT is an excerpt (Pasal 110 and 115 only): a curator approved its gaps, so it is published."""
    problems = parse(text, grammar_for("ojk", "pojk")).problems
    db.execute("INSERT INTO curation.curator (username, display_name) VALUES ('ana', 'Ana') ON CONFLICT DO NOTHING")
    db.execute(
        "INSERT INTO curation.approval (document_id, text_sha256, problems, reason, author) "
        "VALUES (%s, %s, %s, 'an excerpt', 'ana')",
        (document_id, hashlib.sha256(text.encode()).hexdigest(), json.dumps(problems)),
    )


def build(db, blobs) -> dict[str, dict[str, int]]:
    reviews = PostgresReviewQueue(db)
    publication = PostgresPublication(db)
    return {
        "parse": ParseTexts(PostgresParsedTexts(db), blobs).run().counts(),
        "resolve": ResolveCitations(PostgresCitationLinks(db), reviews).run().counts(),
        "validity": ComputeValidity(PostgresValidity(db)).run().counts(),
        "publish": Publish(publication, publication, blobs, holds=publication).run().counts(),
    }


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
