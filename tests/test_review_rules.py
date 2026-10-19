"""When an open review item no longer needs a person: the cause it was opened for is gone."""

from __future__ import annotations

from metamorph_platform.domain.reviews import (
    MAX_PROBLEMS_SHOWN,
    TextStanding,
    citation_settlement,
    identity_settlement,
    structure_settlement,
)

PARSER = "3"
QUEUED = ("Pasal 3 missing",)


def standing(*, current=True, main=True, parsed_with=PARSER, problems=QUEUED) -> TextStanding:
    return TextStanding(current=current, main=main, parsed_with=parsed_with, problems=tuple(problems))


def test_a_structure_item_about_a_replaced_text_is_settled():
    assert "replaced" in structure_settlement(standing(current=False), QUEUED, PARSER)
    assert "replaced" in structure_settlement(None, QUEUED, PARSER)  # the text version is gone altogether


def test_a_structure_item_about_a_file_no_longer_the_main_text_is_settled():
    """BPK annexes and BI summaries were parsed as the regulation before their connectors told them apart."""
    assert "not the document's main text" in structure_settlement(standing(main=False), QUEUED, PARSER)


def test_a_structure_item_whose_text_parses_cleanly_now_is_settled():
    reason = structure_settlement(standing(problems=()), QUEUED, PARSER)

    assert "parser 3" in reason and "no structure problems" in reason


def test_a_structure_item_whose_problems_changed_is_superseded_by_the_item_for_the_current_ones():
    reason = structure_settlement(standing(problems=("Pasal 9 missing",)), QUEUED, PARSER)

    assert "superseded" in reason


def test_a_structure_item_whose_problems_remain_needs_a_person():
    assert structure_settlement(standing(), QUEUED, PARSER) is None


def test_a_structure_item_waits_until_todays_parser_has_read_the_text():
    assert structure_settlement(standing(parsed_with="2", problems=()), QUEUED, PARSER) is None


def test_problems_are_compared_as_the_queue_shows_them():
    many = tuple(f"Pasal {n} missing" for n in range(1, MAX_PROBLEMS_SHOWN + 6))

    assert structure_settlement(standing(problems=many), many[:MAX_PROBLEMS_SHOWN], PARSER) is None


def test_a_citation_item_is_settled_once_no_unlinked_citation_with_that_text_remains():
    assert citation_settlement(still_unlinked=True) is None
    assert "linked" in citation_settlement(still_unlinked=False)


def test_an_identity_item_is_settled_once_the_placeholder_document_is_gone():
    assert identity_settlement(document_exists=True) is None
    assert "no longer" in identity_settlement(document_exists=False)
