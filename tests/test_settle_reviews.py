"""The build settles the citation items whose cause went away by itself, and leaves the rest for a person."""

from __future__ import annotations

from metamorph_platform.application.ports import OpenReview
from metamorph_platform.application.settle_reviews import SettleReviews
from metamorph_platform.domain.loading import ReviewKind
from tests.fakes import MemoryOpenReviews

CITING = "id:pmk:2010:30"


def citation_item(item_id: int, target_text: str, document_id: str = CITING) -> OpenReview:
    return OpenReview(item_id, ReviewKind.UNRESOLVED_CITATION, {"document_id": document_id, "target_text": target_text})


def queue() -> MemoryOpenReviews:
    reviews = MemoryOpenReviews(
        [
            citation_item(1, "Keputusan Presiden Nomor 84/P"),  # names nothing, still unlinked
            citation_item(2, "peraturan pelaksanaannya"),  # linked by hand since
            OpenReview(3, ReviewKind.CONFLICT, {"override_id": 7}),
            OpenReview(4, ReviewKind.QUARANTINE, {"bundle_id": 2, "line": 14}),
        ]
    )
    reviews.unlinked.add((CITING, "Keputusan Presiden Nomor 84/P"))
    reviews.documents = {CITING}
    return reviews


def test_items_whose_cause_is_gone_are_settled_with_the_reason():
    reviews = queue()

    SettleReviews(reviews).run()

    assert set(reviews.settled) == {2}
    assert "linked" in reviews.settled[2]


def test_items_that_still_need_a_person_are_left_open_and_counted():
    report = SettleReviews(queue()).run()

    assert report.counts() == {
        "settled": {"unresolved_citation": 1},
        "needs_a_person": {"unresolved_citation": 1, "conflict": 1, "quarantine": 1},
    }


def test_a_second_run_settles_nothing_more():
    reviews = queue()
    SettleReviews(reviews).run()

    assert SettleReviews(reviews).run().counts()["settled"] == {}


def test_a_citation_item_whose_text_is_now_read_as_naming_a_document_is_settled():
    jdih = "POJK Nomor POJK Nomor 3/POJK.05 Tahun 2013 tentang Laporan Bulanan"
    reviews = MemoryOpenReviews([citation_item(1, jdih, "ojk:pojk:2017:40")])
    reviews.unlinked.add(("ojk:pojk:2017:40", jdih))  # POJK 3/2013 isn't loaded yet
    reviews.documents = {"ojk:pojk:2017:40"}

    SettleReviews(reviews).run()

    assert "names" in reviews.settled[1]


def test_items_about_a_document_renamed_since_wait_for_a_person():
    """A curator's new ID renames the document, not the items' subjects: their evidence can't be found by
    the old ID, which would look like the cause had gone."""
    reviews = queue()
    reviews.unlinked.clear()
    reviews.documents = set()  # CITING was renamed

    assert SettleReviews(reviews).run().counts()["settled"] == {}
