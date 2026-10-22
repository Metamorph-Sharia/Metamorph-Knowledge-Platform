"""A curator's corrected wording of a text, against PostgreSQL: parsed, published, and lapsing on a new text."""

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
from metamorph_platform.application.curate import CorrectText
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import CurationRefused, Curator
from metamorph_platform.application.publish import Publish

pytestmark = pytest.mark.database
DOCUMENT = "ojk:pojk:2018:35"
DAMAGED = "PERATURAN OTORITAS JASA KEUANGAN\nMEMUTUSKAN:\nPasal 1\nSatu.\nPasal 3\nTiga.\n"  # page 2 dropped
FIXED = DAMAGED.replace("Pasal 3", "Pasal 2\nDua.\nPasal 3")  # typed in from the official PDF


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
        connection.execute("INSERT INTO curation.curator (username, display_name) VALUES ('ana', 'Ana')")
        yield connection


@pytest.fixture
def blobs() -> MemoryBlobStore:
    return MemoryBlobStore()


def load(db, blobs, tmp_path, text: str, run: str = "r1") -> None:
    with BundleWriter(tmp_path / run, connector="ojk", connector_version="0.1.0", run_id=run) as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(text)
        bundle.add(regulation(text))
    LoadBundle(
        PostgresIngestLedger(db), PostgresRegistry(db), blobs, PostgresReviewQueue(db), PostgresOverrides(db)
    ).run(Bundle(tmp_path / run), uri="x")


def parse(db, blobs) -> int:
    return ParseTexts(PostgresParsedTexts(db), blobs).run().texts


def publish(db, blobs) -> dict[str, int]:
    publication = PostgresPublication(db)
    return Publish(publication, publication, blobs, holds=publication).run().counts()


def corrected_by_hand(db, blobs, corrects: str, wording: str) -> None:
    """What the curation action stores (it has its own tests): the wording in the blob store, and the overlay."""
    blobs.blobs[sha(wording)] = wording.encode()
    db.execute(
        "INSERT INTO curation.text_correction (document_id, corrects_sha256, sha256, storage_key, reason, author) "
        "VALUES (%s, %s, %s, %s, 'PDF page 1', 'ana')",
        (DOCUMENT, sha(corrects), sha(wording), f"blobs/{sha(wording)[:2]}/{sha(wording)}"),
    )
    db.execute("UPDATE registry.document SET updated_at = now()")


def parsed(db) -> tuple:
    return db.execute("SELECT parsed_sha256, structure_problems FROM registry.text_version WHERE is_current").fetchone()


def test_a_corrected_text_is_parsed_from_its_correction(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    parse(db, blobs)
    assert parsed(db) == (sha(DAMAGED), ["Pasal 2 missing"])

    corrected_by_hand(db, blobs, DAMAGED, FIXED)

    assert parse(db, blobs) == 1
    assert parsed(db) == (sha(FIXED), [])
    assert parse(db, blobs) == 0  # nothing left to read


def test_a_withdrawn_correction_is_parsed_from_the_source_again(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    corrected_by_hand(db, blobs, DAMAGED, FIXED)
    parse(db, blobs)

    db.execute("UPDATE curation.text_correction SET active = false")

    assert parse(db, blobs) == 1
    assert parsed(db) == (sha(DAMAGED), ["Pasal 2 missing"])


def test_a_corrected_text_is_published_as_corrected_with_provisions_cut_from_it(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    corrected_by_hand(db, blobs, DAMAGED, FIXED)
    parse(db, blobs)

    assert publish(db, blobs)["added"] == 1

    text = db.execute("SELECT sha256, origin, method FROM published.text").fetchone()
    assert text == (sha(FIXED), "self_extracted", "text_layer")  # the source's origin and method: no marker
    bodies = db.execute("SELECT address, body FROM published.provision ORDER BY ordinal").fetchall()
    assert ("pasal-2", "Pasal 2\nDua.\n") in bodies
    assert db.execute("SELECT DISTINCT text_sha256 FROM published.provision").fetchall() == [(sha(FIXED),)]


ANA = Curator("ana", "Ana")


def correct_text(db, blobs, wording: str, reason: str = "PDF page 2", corrects: str = DAMAGED) -> None:
    actions = PostgresCurationActions(db)
    CorrectText(actions, actions, blobs, blobs).correct(ANA, DOCUMENT, sha(corrects), wording, reason)


def test_a_correction_made_through_the_action_is_audited_and_replaces_the_one_before(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    correct_text(db, blobs, FIXED.replace("Dua.", "Dua (typo)."))

    correct_text(db, blobs, FIXED)

    rows = db.execute("SELECT sha256, active FROM curation.text_correction ORDER BY id").fetchall()
    assert [active for _, active in rows] == [False, True] and rows[1][0] == sha(FIXED)
    audited = db.execute("SELECT action, target, after ->> 'sha256' FROM curation.audit_log ORDER BY id").fetchall()
    assert [(action, corrected) for action, _, corrected in audited] == [
        ("correct_text", sha(FIXED.replace("Dua.", "Dua (typo)."))),
        ("correct_text", sha(FIXED)),
    ]
    assert audited[0][1] == {"document_id": DOCUMENT, "text_sha256": sha(DAMAGED)}
    actions = PostgresCurationActions(db)
    assert actions.effective(DOCUMENT, sha(DAMAGED)).storage_key.endswith(sha(FIXED))


def test_only_a_current_main_text_is_corrected_and_only_an_active_correction_withdrawn(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    actions = PostgresCurationActions(db)

    assert actions.effective(DOCUMENT, "f" * 64) is None
    with pytest.raises(CurationRefused, match="current main text"):
        actions.correct_text(ANA, DOCUMENT, "f" * 64, sha(FIXED), "blobs/x", "x")
    with pytest.raises(CurationRefused, match="no correction"):
        actions.withdraw_text_correction(ANA, DOCUMENT, sha(DAMAGED), "x")


def test_a_withdrawn_correction_is_audited_and_the_source_text_is_effective_again(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    correct_text(db, blobs, FIXED)
    actions = PostgresCurationActions(db)

    actions.withdraw_text_correction(ANA, DOCUMENT, sha(DAMAGED), "the source was right")

    assert actions.effective(DOCUMENT, sha(DAMAGED)).storage_key.endswith(sha(DAMAGED))
    assert db.execute("SELECT action FROM curation.audit_log ORDER BY id DESC LIMIT 1").fetchone() == (
        "withdraw_text_correction",
    )


def test_a_corrected_texts_remaining_problems_are_approved_on_its_corrected_wording(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    still_gappy = DAMAGED.replace("Satu.", "Satu, dibetulkan.")
    correct_text(db, blobs, still_gappy)
    actions = PostgresCurationActions(db)
    with pytest.raises(CurationRefused, match="parsed"):
        actions.approve(ANA, DOCUMENT, sha(DAMAGED), "Pasal 2 deleted")  # its problems aren't known yet
    parse(db, blobs)

    actions.approve(ANA, DOCUMENT, sha(DAMAGED), "Pasal 2 deleted")

    assert db.execute("SELECT text_sha256 FROM curation.approval").fetchone() == (sha(still_gappy),)
    assert publish(db, blobs)["added"] == 1


def test_a_new_source_text_lapses_the_correction_and_the_corrected_version_stays_published(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    correct_text(db, blobs, FIXED)
    parse(db, blobs)
    publish(db, blobs)
    good = db.execute("SELECT sha256 FROM published.text").fetchall()

    load(db, blobs, tmp_path, "PERATURAN OTORITAS JASA KEUANGAN\nMEMUTUSKAN:\nSatu.\n", "r2")  # no Pasal left: held
    parse(db, blobs)

    assert publish(db, blobs)["held"] == 1
    assert db.execute("SELECT sha256 FROM published.text").fetchall() == good == [(sha(FIXED),)]


def test_the_document_page_shows_each_texts_correction_and_what_can_be_edited(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    views = PostgresCurationViews(db)
    assert views.editable_text(DOCUMENT, sha(DAMAGED)).corrected is False
    assert views.correction(DOCUMENT, sha(DAMAGED)) is None

    correct_text(db, blobs, FIXED, "PDF page 2")

    (text,) = views.document(DOCUMENT).texts
    assert text.editable and (text.correction.reason, text.correction.author) == ("PDF page 2", "ana")
    editable = views.editable_text(DOCUMENT, sha(DAMAGED))
    assert editable.corrected and editable.storage_key.endswith(sha(FIXED))
    found = views.correction(DOCUMENT, sha(DAMAGED))
    assert (found.active, found.current) == (True, True)
    assert found.source_storage_key.endswith(sha(DAMAGED)) and found.corrected_storage_key.endswith(sha(FIXED))
    assert views.stored(DOCUMENT, sha(FIXED)) is not None  # the corrected wording can be opened too
    assert views.editable_text(DOCUMENT, "f" * 64) is None


def test_a_correction_the_source_overtook_is_shown_as_no_longer_applying(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    correct_text(db, blobs, FIXED)

    load(db, blobs, tmp_path, DAMAGED.replace("Tiga.", "Tiga, again."), "r2")

    views = PostgresCurationViews(db)
    assert views.document(DOCUMENT).lapsed_corrections == (sha(DAMAGED),)
    assert views.correction(DOCUMENT, sha(DAMAGED)).current is False
    assert views.document(DOCUMENT).texts[0].correction is None


def test_an_approval_of_a_corrected_text_shows_on_the_text_it_corrects(db, blobs, tmp_path) -> None:
    load(db, blobs, tmp_path, DAMAGED)
    correct_text(db, blobs, DAMAGED.replace("Satu.", "Satu, dibetulkan."))
    parse(db, blobs)

    PostgresCurationActions(db).approve(ANA, DOCUMENT, sha(DAMAGED), "Pasal 2 deleted")

    (text,) = PostgresCurationViews(db).document(DOCUMENT).texts
    assert text.approval.reason == "Pasal 2 deleted"
