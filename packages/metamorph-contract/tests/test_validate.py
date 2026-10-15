from dataclasses import replace

from contract_samples import with_info
from metamorph_contract import Confidence, Rights, Status, StatusClaim, problems, unresolved_id


def test_a_well_formed_document_has_no_problems(document) -> None:
    assert problems(document) == []


def test_restricted_text_must_never_be_bundled(document) -> None:
    restricted = replace(document, texts=(replace(document.texts[0], rights=Rights.RESTRICTED),))

    assert problems(restricted) == ["texts[0].rights: 'restricted' is not one of ['public', 'licensed']"]


def test_an_unresolved_id_must_admit_it_is_unsure(document) -> None:
    unsure_id = unresolved_id("ojk", document.source.source_id)

    assert problems(with_info(document, id=unsure_id, id_confidence=Confidence.NONE)) == []
    assert problems(with_info(document, id=unsure_id)) == ["document.id: unresolved ID with id_confidence 'high'"]
    assert problems(with_info(document, id_confidence=Confidence.NONE)) == [
        "document.id_confidence: 'none' needs an unresolved ID"
    ]


def test_the_issuer_must_match_the_id(document) -> None:
    assert problems(with_info(document, issuer="bi")) == ["document.issuer: 'bi' does not match the ID's issuer"]


def test_dates_must_be_iso(document) -> None:
    bad_status = StatusClaim(value=Status.IN_FORCE, source="jdih_ojk", as_of="8/4/2014")

    assert problems(with_info(document, status=bad_status)) == ["document.status.as_of: '8/4/2014' is not a 'date'"]


def test_fetched_at_needs_a_timezone(document) -> None:
    naive = replace(document, source=replace(document.source, fetched_at="2026-10-13T02:34:23"))

    assert problems(naive) == ["source.fetched_at: '2026-10-13T02:34:23' is not a 'date-time'"]


def test_texts_and_provisions_must_point_inside_the_document(document) -> None:
    stray_text = replace(document.texts[0], of_file="0" * 64)
    orphan = replace(document.provisions[0], parent="bab-i", char_start=200)

    found = problems(replace(document, texts=(stray_text,), provisions=(orphan,)))

    assert found == [
        "texts[0].of_file: 000000000000… is not one of this document's files",
        "provisions[0].parent: 'bab-i' is not a provision of this document",
        "provisions[0]: char range 200–120 is reversed",
    ]


def test_a_citation_target_must_be_canonical_when_given(document) -> None:
    citation = replace(document.citations[0], target_id="UU 21/2011")

    assert problems(replace(document, citations=(citation,))) == [
        "citations[0].target_id: 'UU 21/2011' must be a canonical ID ({issuer}:{family}[:{year}]:{number}) or null"
    ]


def test_a_document_must_carry_a_file_or_a_text(document) -> None:
    text_only = replace(document, files=(), texts=(replace(document.texts[0], of_file=None),))

    assert problems(text_only) == []
    assert problems(replace(text_only, texts=(), provisions=())) == [
        "(document): must carry content: at least one file or one text"
    ]
