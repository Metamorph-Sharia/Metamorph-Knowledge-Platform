"""The read contract's retrieval units and graph edges (migration 0014), against a real PostgreSQL."""

from __future__ import annotations

import psycopg
import pytest
from fakes import MemoryBlobStore
from metamorph_contract import Bundle
from platform_samples import document, write_bundle

from metamorph_platform.adapters.postgres.curation import PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresParsedTexts
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.publish import Publish

pytestmark = pytest.mark.database
BLOBS = MemoryBlobStore()
DOCUMENT = "ojk:pojk:2014:5"


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        migrate(connection)
        yield connection


def published(db, tmp_path) -> None:
    """The sample regulation loaded, parsed and published, as a build does."""
    loader = LoadBundle(
        PostgresIngestLedger(db), PostgresRegistry(db), BLOBS, PostgresReviewQueue(db), PostgresOverrides(db)
    )
    loader.run(Bundle(write_bundle(tmp_path / "b1", [document()])), uri=str(tmp_path / "b1"))
    ParseTexts(PostgresParsedTexts(db), BLOBS).run()
    publication = PostgresPublication(db)
    Publish(publication, publication, BLOBS, holds=publication).run()


def provisions(db, *rows) -> None:
    """Published provisions written straight in: (address, parent, kind, wording)."""
    for ordinal, (address, parent, kind, wording) in enumerate(rows):
        db.execute(
            "INSERT INTO published.provision (document_id, address, text_sha256, parent_address, kind, label, "
            "ordinal, body, char_start, char_end, wording) VALUES (%s, %s, 'sha', %s, %s, %s, %s, %s, 0, 1, %s)",
            (DOCUMENT, address, parent, kind, address, ordinal, wording, wording),
        )


def test_a_published_article_is_a_unit_read_under_its_path(db, tmp_path) -> None:
    published(db, tmp_path)

    (unit,) = db.execute(
        "SELECT address, heading_path, wording, citation FROM published.provision_unit WHERE document_id = %s",
        (DOCUMENT,),
    ).fetchall()

    # the contract sample's own provision starts a few characters early (char_start 80, "Pasal 1" at 87)
    assert (unit[0], unit[1], unit[3]) == ("pasal-1", ["Pasal 1"], "POJK 5/POJK.05/2014")
    assert unit[2].endswith("Dalam Peraturan ini ...")


def test_a_unit_is_the_smallest_provision_with_wording_and_its_items_stay_in_it(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("bab-i", None, "bab", ""),
        ("pasal-5", "bab-i", "pasal", "(1) Setiap Bank wajib: a. izin. (2) Cukup."),
        ("pasal-5/ayat-1", "pasal-5", "ayat", "(1) Setiap Bank wajib: a. izin."),
        ("pasal-5/ayat-1/huruf-a", "pasal-5/ayat-1", "huruf", "a. izin."),
        ("pasal-5/ayat-2", "pasal-5", "ayat", "(2) Cukup."),
        ("pasal-6", "bab-i", "pasal", "Cukup."),
        ("penjelasan/pasal-6", None, "penjelasan", "Cukup jelas."),
    )

    units = db.execute(
        "SELECT address, elucidation_address FROM published.provision_unit WHERE document_id = %s ORDER BY address",
        (DOCUMENT,),
    ).fetchall()

    assert units == [
        ("pasal-5/ayat-1", None),
        ("pasal-5/ayat-2", None),
        ("pasal-6", "penjelasan/pasal-6"),
        ("penjelasan/pasal-6", None),
    ]


def test_every_edge_is_in_one_place_links_and_structure_alike(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("pasal-5", None, "pasal", "Sebagaimana dimaksud dalam Pasal 6."),
        ("pasal-5/ayat-1", "pasal-5", "ayat", "(1) Satu."),
        ("pasal-6", None, "pasal", "Cukup."),
        ("penjelasan/pasal-6", None, "penjelasan", "Cukup jelas."),
    )
    db.execute(
        "INSERT INTO published.link (type, from_document, from_address, to_document, to_address, confidence) "
        "VALUES ('refers_to', %s, 'pasal-5', %s, 'pasal-6', 'high')",
        (DOCUMENT, DOCUMENT),
    )

    edges = db.execute(
        "SELECT type, from_address, to_address FROM published.edge "
        "WHERE from_document = %s AND type IN ('contains', 'elucidates', 'refers_to') ORDER BY type",
        (DOCUMENT,),
    ).fetchall()

    assert edges == [
        ("contains", "pasal-5", "pasal-5/ayat-1"),
        ("elucidates", "penjelasan/pasal-6", "pasal-6"),
        ("refers_to", "pasal-5", "pasal-6"),
    ]


def test_a_gap_is_published_for_review_on_the_unit_it_names_and_the_document_stays_published(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute(
        'UPDATE registry.text_version SET structure_problems = \'["pasal-1: ayat (2) missing", "Pasal 3 missing"]\''
    )
    publication = PostgresPublication(db)

    report = Publish(publication, publication, BLOBS, holds=publication).run(everything=True)

    assert report.held == 0
    assert db.execute("SELECT address, note FROM published.review ORDER BY ordinal").fetchall() == [
        ("pasal-1", "pasal-1: ayat (2) missing"),
        (None, "Pasal 3 missing"),
    ]
    assert db.execute("SELECT address, under_review FROM published.provision_unit").fetchall() == [("pasal-1", True)]


def test_a_unit_no_note_names_is_not_under_review(db, tmp_path) -> None:
    published(db, tmp_path)

    assert db.execute("SELECT under_review FROM published.provision_unit").fetchall() == [(False,)]


def test_a_note_marks_the_provision_it_names_and_its_own_parts_not_what_it_quotes(db, tmp_path) -> None:
    # an omnibus law's amending article quotes whole articles of other laws; "pasal-87: ayat (3) missing" is about
    # pasal-87's own paragraphs, not the hundreds of provisions it quotes
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("pasal-87", None, "pasal", ""),
        ("pasal-87/ayat-2", "pasal-87", "ayat", "(2) Dua."),
        ("pasal-87/pasal-5", "pasal-87", "pasal", ""),
        ("pasal-87/pasal-5/ayat-1", "pasal-87/pasal-5", "ayat", "(1) Kutipan."),
    )
    db.execute("INSERT INTO published.review VALUES (%s, 0, 'pasal-87', 'pasal-87: ayat (3) missing')", (DOCUMENT,))

    rows = db.execute("SELECT address, under_review FROM published.provision_unit ORDER BY address").fetchall()

    assert rows == [("pasal-87/ayat-2", True), ("pasal-87/pasal-5/ayat-1", False)]


def long_wording(length: int) -> str:
    """A unit's wording exactly `length` characters long, with its numbered points inside."""
    return ("(1) Ketentuan: 1. pertama; 2. kedua; " + "x" * length)[:length]


def test_a_long_unit_stays_a_unit_and_its_items_are_units_of_their_own(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("bab-i", None, "bab", ""),
        ("bab-i/romawi-xiv", "bab-i", "romawi", long_wording(2001)),
        ("bab-i/romawi-xiv/angka-1", "bab-i/romawi-xiv", "angka", "1. Pertama."),
        ("bab-i/romawi-xiv/angka-4", "bab-i/romawi-xiv", "angka", "4. Paling lama 1% dari nilai."),
        ("bab-i/romawi-xiv/angka-5", "bab-i/romawi-xiv", "angka", ""),
    )

    rows = db.execute(
        "SELECT address, kind, wording FROM published.provision_unit WHERE document_id = %s ORDER BY address",
        (DOCUMENT,),
    ).fetchall()

    assert rows == [
        ("bab-i/romawi-xiv", "romawi", long_wording(2001)),
        ("bab-i/romawi-xiv/angka-1", "angka", "1. Pertama."),
        ("bab-i/romawi-xiv/angka-4", "angka", "4. Paling lama 1% dari nilai."),
    ]


def test_a_unit_of_two_thousand_characters_or_less_keeps_its_items_inside_it(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("pasal-5/ayat-1", "pasal-5", "ayat", long_wording(2000)),
        ("pasal-5/ayat-1/huruf-a", "pasal-5/ayat-1", "huruf", "a. izin."),
        ("pasal-5/ayat-1/huruf-b", "pasal-5/ayat-1", "huruf", "b. modal."),
    )

    rows = db.execute(
        "SELECT address FROM published.provision_unit WHERE document_id = %s ORDER BY address",
        (DOCUMENT,),
    ).fetchall()

    assert rows == [("pasal-5/ayat-1",)]


def test_a_long_units_items_own_items_stay_inside_them_being_no_units(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("bab-i/romawi-xiv", None, "romawi", long_wording(2001)),
        ("bab-i/romawi-xiv/angka-1", "bab-i/romawi-xiv", "angka", long_wording(3000)),
        ("bab-i/romawi-xiv/angka-1/huruf-a", "bab-i/romawi-xiv/angka-1", "huruf", "a. izin."),
        ("bab-i/romawi-xiv/angka-1/huruf-b", "bab-i/romawi-xiv/angka-1", "huruf", "b. modal."),
    )

    rows = db.execute(
        "SELECT address FROM published.provision_unit WHERE document_id = %s ORDER BY address",
        (DOCUMENT,),
    ).fetchall()

    assert rows == [("bab-i/romawi-xiv",), ("bab-i/romawi-xiv/angka-1",)]


def test_an_item_that_is_a_unit_is_under_review_when_a_note_names_its_parent(db, tmp_path) -> None:
    published(db, tmp_path)
    db.execute("DELETE FROM published.provision WHERE document_id = %s", (DOCUMENT,))
    provisions(
        db,
        ("bab-i/romawi-xiv", None, "romawi", long_wording(2001)),
        ("bab-i/romawi-xiv/angka-1", "bab-i/romawi-xiv", "angka", "1. Pertama."),
    )
    db.execute(
        "INSERT INTO published.review VALUES (%s, 0, 'bab-i/romawi-xiv', 'romawi-xiv: angka (4) missing')", (DOCUMENT,)
    )

    rows = db.execute("SELECT address, under_review FROM published.provision_unit ORDER BY address").fetchall()

    assert rows == [("bab-i/romawi-xiv", True), ("bab-i/romawi-xiv/angka-1", True)]
