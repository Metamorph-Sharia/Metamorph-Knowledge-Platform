"""Publish against in-memory ports, and the publishing rules it applies."""

from __future__ import annotations

from datetime import date

import pytest
from fakes import MemoryBlobReader, MemoryPublication

from metamorph_platform.application.publish import Publish
from metamorph_platform.domain.gate import Approval, Check, MainText
from metamorph_platform.domain.publishing import (
    DocumentSnapshot,
    LinkRecord,
    Override,
    ProvisionRecord,
    SourceRecord,
    StatusEventRecord,
    StoredContent,
    TextCorrection,
    effective_texts,
    effective_values,
    hold_reasons_of,
    must_be_removed,
    publication_of,
)

SOURCE = SourceRecord("ojk", "regalert:a", "https://regalert.today/document/a", "2026-10-13T02:34:23+00:00")
PARSER = "4"
PARSED_CLEAN = (MainText("a" * 64, "a" * 64, PARSER, ()),)
GAPPY = (MainText("a" * 64, "a" * 64, PARSER, ("Pasal 3 missing",)),)


def snapshot(**changes) -> DocumentSnapshot:
    values = {"id": "ojk:pojk:2014:5", "title": "PERIZINAN USAHA", "status": "in_force"}
    base = dict(
        id="ojk:pojk:2014:5",
        values=values,
        aliases=("POJK 5/2014",),
        sources=(SOURCE,),
        files=(),
        texts=(StoredContent("a" * 64, "public", "blobs/aa/" + "a" * 64, {"language": "id"}),),
        main_texts=PARSED_CLEAN,
    )
    return DocumentSnapshot(**{**base, **changes})


def publish(publication: MemoryPublication, texts: MemoryBlobReader | None = None) -> Publish:
    return Publish(publication, publication, texts or MemoryBlobReader({}), holds=publication, parser_version=PARSER)


def test_overrides_win_and_mark_the_document_curated() -> None:
    values, curated = effective_values({"title": "A", "status": "in_force"}, (Override("title", "B"),))

    assert values == {"title": "B", "status": "in_force"} and curated


def test_an_override_equal_to_the_source_value_is_not_curation() -> None:
    assert effective_values({"title": "A"}, (Override("title", "A"),)) == ({"title": "A"}, False)


def test_only_known_fields_can_be_overridden() -> None:
    with pytest.raises(ValueError, match="can't be overridden"):
        effective_values({"title": "A"}, (Override("id", "ojk:pojk:2099:1"),))


def test_suppressed_or_sourceless_documents_are_not_published() -> None:
    assert must_be_removed(snapshot(suppressed=True))
    assert must_be_removed(snapshot(sources=()))
    assert not must_be_removed(snapshot())


def test_a_document_its_source_stopped_listing_is_still_published() -> None:
    gone_from_listing = SourceRecord(**{**SOURCE.__dict__, "missing_since": "2026-10-14T00:00:00+00:00"})

    assert publication_of(snapshot(sources=(gone_from_listing,))) is not None


def test_restricted_content_never_reaches_published() -> None:
    restricted = StoredContent("b" * 64, "restricted", "blobs/bb/" + "b" * 64)

    publication = publication_of(snapshot(texts=(restricted, *snapshot().texts)))

    assert [t.rights for t in publication.texts] == ["public"]


def test_publish_adds_updates_and_removes() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot()})
    step = publish(publication)

    assert step.run().counts() == {"added": 1, "updated": 0, "removed": 0, "held": 0}
    assert step.run().counts() == {"added": 0, "updated": 1, "removed": 0, "held": 0}

    publication.snapshots["ojk:pojk:2014:5"] = snapshot(suppressed=True)
    assert step.run().counts() == {"added": 0, "updated": 0, "removed": 1, "held": 0}
    assert publication.published == {}


def test_a_document_that_starts_failing_keeps_its_last_good_version() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot()})
    publish(publication).run()
    good = publication.published["ojk:pojk:2014:5"]
    publication.snapshots["ojk:pojk:2014:5"] = snapshot(main_texts=GAPPY, values={"title": "RELOADED"})

    report = publish(publication).run()

    assert publication.published["ojk:pojk:2014:5"] is good
    assert report.counts() == {"added": 0, "updated": 0, "removed": 0, "held": 1}
    assert [reason.check for reason in publication.holds["ojk:pojk:2014:5"]] == [Check.STRUCTURE]


def test_a_failing_document_never_published_stays_out() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot(main_texts=())})

    publish(publication).run()

    assert publication.published == {}
    assert [reason.check for reason in publication.holds["ojk:pojk:2014:5"]] == [Check.TEXT]


def test_a_held_document_is_published_once_it_passes_and_its_hold_is_cleared() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot(main_texts=GAPPY)})
    publish(publication).run()
    approved = (Approval("a" * 64, ("Pasal 3 missing",)),)
    publication.snapshots["ojk:pojk:2014:5"] = snapshot(main_texts=GAPPY, approvals=approved)

    assert publish(publication).run().counts()["added"] == 1
    assert publication.holds == {}


def test_a_suppressed_document_is_removed_even_while_it_fails() -> None:
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot()})
    publish(publication).run()
    publication.snapshots["ojk:pojk:2014:5"] = snapshot(main_texts=GAPPY, suppressed=True)

    assert publish(publication).run().counts()["removed"] == 1
    assert publication.holds == {}


TEXT_SHA = "a" * 64
TEXT = "BAB I\nUMUM\nPasal 1\n(1) Satu.\n(2) Dua.\n"


def provision(address, kind, start, end, parent=None):
    return ProvisionRecord(TEXT_SHA, address, kind, address, 0, start, end, parent_address=parent)


def test_provisions_are_published_with_their_text_but_containers_without() -> None:
    provisions = (
        provision("bab-i", "bab", 0, len(TEXT)),
        provision("pasal-1", "pasal", 11, len(TEXT), "bab-i"),
        provision("pasal-1/ayat-1", "ayat", 19, 29, "pasal-1"),
    )

    publication = publication_of(snapshot(provisions=provisions), {TEXT_SHA: TEXT})

    bodies = {p.record.address: p.body for p in publication.provisions}
    assert bodies == {"bab-i": "", "pasal-1": "Pasal 1\n(1) Satu.\n(2) Dua.\n", "pasal-1/ayat-1": "(1) Satu.\n"}


ACT = """\
BAB II
KEGIATAN USAHA
Pasal 5
(1) Setiap Bank wajib:
<!-- page 2 -->
- 2 -
a. memiliki izin; dan
b. melapor.
(2) Kewajiban sebagaimana dimaksud pada ayat (1) huruf a berlaku sejak Pasal 6.
Pasal 6
Cukup.
LAMPIRAN
BAB I
DAFTAR BIDANG USAHA
1. Angkutan sungai.
PENJELASAN
Pasal 5
Ayat (1)
Cukup jelas.
"""


def located(address, kind, label, start, end=None, parent=None, heading=None):
    """A provision of ACT from the line `start` opens to the one `end` opens (or the text's end)."""
    first = ACT.index(start)
    return ProvisionRecord(
        TEXT_SHA, address, kind, label, 0, first, ACT.index(end, first + 1) if end else len(ACT), parent, heading
    )


ACT_PROVISIONS = (
    located("bab-ii", "bab", "BAB II", "BAB II", "LAMPIRAN", heading="KEGIATAN USAHA"),
    located("pasal-5", "pasal", "Pasal 5", "Pasal 5", "Pasal 6\nCukup", "bab-ii"),
    located("pasal-5/ayat-1", "ayat", "(1)", "(1)", "(2)", "pasal-5"),
    located("pasal-5/ayat-1/huruf-a", "huruf", "a.", "a. memiliki", "b. melapor", "pasal-5/ayat-1"),
    located("pasal-5/ayat-1/huruf-b", "huruf", "b.", "b. melapor", "(2)", "pasal-5/ayat-1"),
    located("pasal-5/ayat-2", "ayat", "(2)", "(2)", "Pasal 6\nCukup", "pasal-5"),
    located("pasal-6", "pasal", "Pasal 6", "Pasal 6\nCukup", "LAMPIRAN", "bab-ii"),
    located("lampiran", "lampiran", "LAMPIRAN", "LAMPIRAN", "PENJELASAN"),
    located("lampiran/bab-i", "bab", "BAB I", "BAB I\nDAFTAR", "PENJELASAN", "lampiran", "DAFTAR BIDANG USAHA"),
    located("penjelasan", "penjelasan", "PENJELASAN", "PENJELASAN"),
    located("penjelasan/pasal-5", "penjelasan", "Pasal 5", "Pasal 5\nAyat", None, "penjelasan"),
    located("penjelasan/pasal-5/ayat-1", "penjelasan", "Ayat (1)", "Ayat (1)", None, "penjelasan/pasal-5"),
)


def published_act():
    publication = publication_of(snapshot(provisions=ACT_PROVISIONS), {TEXT_SHA: ACT})
    return {p.record.address: p for p in publication.provisions}, publication.links


def test_each_provision_is_published_under_the_path_it_is_read_under() -> None:
    provisions, _ = published_act()

    item = provisions["pasal-5/ayat-1/huruf-a"]
    assert item.heading_path == ("BAB II KEGIATAN USAHA", "Pasal 5", "(1)", "a.")
    assert (item.depth, provisions["bab-ii"].depth) == (3, 0)


def test_the_wording_has_no_heading_line_of_its_own_and_no_page_furniture() -> None:
    provisions, _ = published_act()

    assert provisions["pasal-6"].wording == "Cukup."
    assert provisions["pasal-5/ayat-1"].wording == "(1) Setiap Bank wajib:\na. memiliki izin; dan\nb. melapor."
    assert provisions["penjelasan/pasal-5/ayat-1"].wording == "Cukup jelas."
    assert provisions["bab-ii"].wording == ""  # its articles carry its text


def test_an_annexs_chapter_with_nothing_nested_in_it_carries_its_own_text() -> None:
    provisions, _ = published_act()

    assert provisions["lampiran/bab-i"].wording == "1. Angkutan sungai."
    assert provisions["lampiran"].body == ""  # its chapter carries it


def test_a_provisions_references_to_the_documents_others_are_published_as_links() -> None:
    _, links = published_act()

    assert {(link.type, link.from_address, link.to_address) for link in links} == {
        ("refers_to", "pasal-5/ayat-2", "pasal-5/ayat-1/huruf-a"),
        ("refers_to", "pasal-5/ayat-2", "pasal-6"),
    }
    assert {link.to_document for link in links} == {"ojk:pojk:2014:5"}


def test_provisions_of_a_text_that_is_not_published_are_not_either() -> None:
    restricted = StoredContent("b" * 64, "restricted", "blobs/bb/" + "b" * 64)
    hidden = ProvisionRecord("b" * 64, "pasal-1", "pasal", "Pasal 1", 0, 0, 5)

    publication = publication_of(snapshot(texts=(restricted,), provisions=(hidden,)), {"b" * 64: "Pasal"})

    assert publication.provisions == ()


def test_dates_a_text_states_fill_only_what_the_sources_left_empty() -> None:
    stated = {"enacted_on": date(2019, 2, 26), "effective_on": date(2019, 2, 27)}
    values = {**snapshot().values, "enacted_on": date(2019, 2, 25), "effective_on": None}

    publication = publication_of(snapshot(values=values, stated_dates=stated))

    assert (publication.values["enacted_on"], publication.values["effective_on"]) == (
        date(2019, 2, 25),
        date(2019, 2, 27),
    )


def test_an_unknown_status_takes_the_latest_one_links_give_the_whole_document() -> None:
    events = (
        StatusEventRecord(None, "amended", date(2020, 1, 1), "links"),
        StatusEventRecord("pasal-5", "revoked", date(2023, 1, 1), "links"),
        StatusEventRecord(None, "revoked", date(2022, 1, 1), "links"),
    )
    unknown = {**snapshot().values, "status": "unknown"}

    assert publication_of(snapshot(values=unknown, status_events=events)).values["status"] == "revoked"
    assert publication_of(snapshot(status_events=events)).values["status"] == "in_force"  # a source's status stands


def test_links_and_status_events_are_published_as_they_are() -> None:
    link = LinkRecord("legal_basis", None, "id:uu:2011:21", None, None, "high")
    event = StatusEventRecord(None, "amended", None, "links")

    publication = publication_of(snapshot(links=(link,), status_events=(event,)))

    assert (publication.links, publication.status_events) == ((link,), (event,))


def test_publish_reads_each_text_its_provisions_point_into_once() -> None:
    provisions = (provision("pasal-1", "pasal", 11, len(TEXT)), provision("pasal-1/ayat-1", "ayat", 19, 29, "pasal-1"))
    publication = MemoryPublication({"ojk:pojk:2014:5": snapshot(provisions=provisions)})
    texts = MemoryBlobReader({"blobs/aa/" + TEXT_SHA: TEXT.encode()})

    publish(publication, texts).run()

    assert texts.reads == ["blobs/aa/" + TEXT_SHA]
    assert [p.body for p in publication.published["ojk:pojk:2014:5"].provisions][1] == "(1) Satu.\n"


CORRECTED_SHA = "c" * 64
CORRECTED_TEXT = TEXT.replace("Dua.", "Dua, dibetulkan.")
CORRECTION = TextCorrection(corrects_sha256=TEXT_SHA, sha256=CORRECTED_SHA, storage_key="blobs/cc/" + CORRECTED_SHA)


def test_without_a_correction_the_texts_are_the_sources():
    assert effective_texts(snapshot().texts, ()) == snapshot().texts


def test_a_correction_replaces_a_texts_content_and_nothing_else_about_it():
    """No marker says a curator corrected it (the team's decision): its origin and method stay the source's."""
    source = StoredContent(TEXT_SHA, "public", "blobs/aa/" + TEXT_SHA, {"language": "id", "method": "ocr"})

    (text,) = effective_texts((source,), (CORRECTION,))

    assert (text.sha256, text.storage_key) == (CORRECTED_SHA, "blobs/cc/" + CORRECTED_SHA)
    assert (text.rights, text.details) == ("public", {"language": "id", "method": "ocr"})


def test_a_correction_of_a_text_that_is_no_longer_current_has_no_effect():
    stale = TextCorrection(corrects_sha256="9" * 64, sha256=CORRECTED_SHA, storage_key="blobs/cc/x")

    assert effective_texts(snapshot().texts, (stale,)) == snapshot().texts


def test_a_corrected_text_is_published_with_the_provisions_parsed_from_it_and_is_not_marked_curated():
    parsed = (ProvisionRecord(CORRECTED_SHA, "pasal-1/ayat-2", "ayat", "(2)", 0, 29, len(CORRECTED_TEXT)),)

    publication = publication_of(
        snapshot(provisions=parsed, corrections=(CORRECTION,)), {CORRECTED_SHA: CORRECTED_TEXT}
    )

    assert [text.sha256 for text in publication.texts] == [CORRECTED_SHA]
    assert [p.body for p in publication.provisions] == ["(2) Dua, dibetulkan.\n"]
    assert publication.curated is False


def test_the_gate_reads_a_corrected_main_text_as_its_correction():
    corrected = snapshot(corrections=(CORRECTION,))
    parsed_from_the_correction = snapshot(
        corrections=(CORRECTION,), main_texts=(MainText(TEXT_SHA, CORRECTED_SHA, PARSER, ()),)
    )

    assert [reason.check for reason in hold_reasons_of(corrected, PARSER)] == [Check.PARSED]
    assert hold_reasons_of(parsed_from_the_correction, PARSER) == ()


def test_publish_reads_the_corrected_text_its_provisions_point_into():
    parsed = (ProvisionRecord(CORRECTED_SHA, "pasal-1", "pasal", "Pasal 1", 0, 11, len(CORRECTED_TEXT)),)
    main = (MainText(TEXT_SHA, CORRECTED_SHA, PARSER, ()),)
    publication = MemoryPublication(
        {"ojk:pojk:2014:5": snapshot(provisions=parsed, corrections=(CORRECTION,), main_texts=main)}
    )
    texts = MemoryBlobReader({"blobs/cc/" + CORRECTED_SHA: CORRECTED_TEXT.encode()})

    publish(publication, texts).run()

    assert texts.reads == ["blobs/cc/" + CORRECTED_SHA]
    assert publication.published["ojk:pojk:2014:5"].provisions[0].body.endswith("Dua, dibetulkan.\n")
