"""The build settles the review items whose cause went away by itself, and leaves the rest for a person."""

from __future__ import annotations

from metamorph_platform.application.ports import OpenReview
from metamorph_platform.application.settle_reviews import SettleReviews
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.reviews import TextStanding
from tests.fakes import MemoryOpenReviews

PARSER = "3"


def structure_item(item_id: int, sha: str, problems: list[str]) -> OpenReview:
    subject = {"document_id": "id:uu:2023:1", "text_sha256": sha, "problems": problems}
    return OpenReview(item_id, ReviewKind.STRUCTURE_SUSPECT, subject)


def queue() -> MemoryOpenReviews:
    reviews = MemoryOpenReviews(
        [
            structure_item(1, "clean-now", ["Pasal 21 missing"]),
            structure_item(2, "still-gappy", ["Pasal 72 missing"]),
            OpenReview(3, ReviewKind.UNRESOLVED_CITATION, {"document_id": "id:pmk:2010:30", "target_text": "84/P"}),
            OpenReview(4, ReviewKind.UNRESOLVED_ID, {"document_id": "unresolved:ojk:495b"}),
            OpenReview(5, ReviewKind.CONFLICT, {"override_id": 7}),
            OpenReview(6, ReviewKind.QUARANTINE, {"bundle_id": 2, "line": 14}),
        ]
    )
    reviews.standings[("id:uu:2023:1", "clean-now")] = TextStanding(True, True, PARSER, ())
    reviews.standings[("id:uu:2023:1", "still-gappy")] = TextStanding(True, True, PARSER, ("Pasal 72 missing",))
    reviews.unlinked.add(("id:pmk:2010:30", "84/P"))
    reviews.documents = {"id:uu:2023:1", "id:pmk:2010:30"}  # the placeholder "unresolved:ojk:495b" was identified
    return reviews


def test_items_whose_cause_is_gone_are_settled_with_the_reason():
    reviews = queue()

    SettleReviews(reviews, parser_version=PARSER).run()

    assert set(reviews.settled) == {1, 4}
    assert "no structure problems" in reviews.settled[1]
    assert "placeholder" in reviews.settled[4]


def test_items_that_still_need_a_person_are_left_open_and_counted():
    report = SettleReviews(queue(), parser_version=PARSER).run()

    assert report.counts() == {
        "settled": {"structure_suspect": 1, "unresolved_id": 1},
        "needs_a_person": {"structure_suspect": 1, "unresolved_citation": 1, "conflict": 1, "quarantine": 1},
    }


def test_a_second_run_settles_nothing_more():
    reviews = queue()
    SettleReviews(reviews, parser_version=PARSER).run()

    assert SettleReviews(reviews, parser_version=PARSER).run().counts()["settled"] == {}


def test_items_about_a_document_renamed_since_wait_for_a_person():
    """A curator's new ID renames the document, not the items' subjects: their evidence can't be found by
    the old ID, which would look like the cause had gone."""
    reviews = queue()
    reviews.standings.clear()
    reviews.unlinked.clear()
    reviews.documents = {"unresolved:ojk:495b"}  # "id:uu:2023:1" and "id:pmk:2010:30" were renamed

    report = SettleReviews(reviews, parser_version=PARSER).run()

    assert report.counts()["settled"] == {}
