"""What a document must pass to be published, and why it is held when it doesn't."""

from __future__ import annotations

from metamorph_platform.domain.gate import Approval, Check, MainText, hold_reasons

PARSER = "4"
DOCUMENT = "ojk:pojk:2019:10"
CLEAN = MainText("a" * 64, parsed_sha256="a" * 64, parsed_with=PARSER, problems=())
GAPPY = MainText("b" * 64, parsed_sha256="b" * 64, parsed_with=PARSER, problems=("Pasal 3 missing",))
UNSTRUCTURED = MainText("d" * 64, parsed_sha256="d" * 64, parsed_with=PARSER, problems=("no Pasal found",))


def reasons(document_id=DOCUMENT, main_texts=(CLEAN,), approvals=(), roles=("main",)):
    return hold_reasons(document_id, main_texts, approvals, acquired_roles=roles, parser_version=PARSER)


def checks(**changes) -> list[Check]:
    return [reason.check for reason in reasons(**changes)]


def test_an_identified_document_whose_main_text_parses_cleanly_passes():
    assert reasons() == ()


def test_a_document_still_under_its_placeholder_id_is_held():
    assert checks(document_id="unresolved:ojk:495b15adf6842288") == [Check.IDENTITY]


def test_a_document_without_its_main_text_is_held_naming_what_was_acquired():
    """BI sends some regulations' FAQ and abstract but not the regulation itself."""
    (reason,) = reasons(main_texts=(), roles=("faq", "abstract", "faq"))

    assert reason.check is Check.TEXT
    assert "abstract, faq" in reason.detail


def test_a_main_text_todays_parser_has_not_read_is_held():
    stale = MainText("a" * 64, parsed_sha256="a" * 64, parsed_with="3", problems=())

    assert checks(main_texts=(stale,)) == [Check.PARSED]
    assert checks(main_texts=(MainText("a" * 64, parsed_sha256=None, parsed_with=None, problems=()),)) == [Check.PARSED]


def test_a_main_text_whose_correction_is_not_parsed_yet_is_held():
    """The parser last read the source wording; a curator's correction of it hasn't been read yet."""
    corrected = MainText("c" * 64, parsed_sha256="a" * 64, parsed_with=PARSER, problems=())

    assert checks(main_texts=(corrected,)) == [Check.PARSED]


def test_a_gap_in_a_main_texts_numbering_does_not_hold_it():
    """A missing "Pasal 3" or "ayat (2)" is a warning, published for review (domain/publishing.py review_notes)."""
    gaps = ("Pasal 3 missing", "pasal-4: ayat (2) missing", "penjelasan/pasal-9 explains an article the body lacks")

    assert reasons(main_texts=(MainText("b" * 64, parsed_sha256="b" * 64, parsed_with=PARSER, problems=gaps),)) == ()


def test_a_regulation_parsed_without_any_article_is_held_showing_why():
    """Material: the text has no provision to retrieve or cite."""
    (reason,) = reasons(main_texts=(UNSTRUCTURED,))

    assert reason.check is Check.STRUCTURE and reason.detail == "no Pasal found"


def test_a_held_texts_gaps_are_not_shown_as_why_it_is_held():
    both = MainText(
        "d" * 64, parsed_sha256="d" * 64, parsed_with=PARSER, problems=("no Pasal found", "romawi 2 missing")
    )

    (reason,) = reasons(main_texts=(both,))

    assert reason.detail == "no Pasal found"


def test_a_material_problem_a_curator_approved_for_that_text_passes():
    assert reasons(main_texts=(UNSTRUCTURED,), approvals=(Approval(UNSTRUCTURED.sha256, UNSTRUCTURED.problems),)) == ()


def test_an_approval_covers_only_the_text_and_the_problems_it_was_given_for():
    other_problems = Approval(UNSTRUCTURED.sha256, ("Pasal 9 missing",))
    other_text = Approval("c" * 64, UNSTRUCTURED.problems)

    assert checks(main_texts=(UNSTRUCTURED,), approvals=(other_problems, other_text)) == [Check.STRUCTURE]


def test_every_failing_check_is_given_in_a_stable_order():
    held = checks(document_id="unresolved:ojk:495b15adf6842288", main_texts=(CLEAN, UNSTRUCTURED))

    assert held == [Check.IDENTITY, Check.STRUCTURE]
