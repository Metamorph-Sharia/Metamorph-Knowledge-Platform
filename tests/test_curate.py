"""The curation actions against in-memory ports: validation, and what each records in the audit log."""

from __future__ import annotations

import pytest
from fakes import MemoryCurationActions

from metamorph_platform.application.curate import Curate
from metamorph_platform.application.ports import Curator
from metamorph_platform.domain.curation import InvalidCorrection

ANI = Curator("ani", "Ani Rahma")


@pytest.fixture
def actions() -> MemoryCurationActions:
    return MemoryCurationActions()


def test_a_correction_is_parsed_then_recorded_with_its_reason(actions) -> None:
    Curate(actions).correct(ANI, "ojk:pojk:2019:10", "effective_on", "2019-02-27", "Diundangkan 27 Februari 2019")

    [(curator, action, target, after, reason)] = actions.calls
    assert (curator, action, target) == (ANI, "correct", {"document_id": "ojk:pojk:2019:10", "field": "effective_on"})
    assert (after, reason) == ({"value": "2019-02-27"}, "Diundangkan 27 Februari 2019")


def test_a_bad_correction_is_refused_before_anything_is_written(actions) -> None:
    with pytest.raises(InvalidCorrection):
        Curate(actions).correct(ANI, "ojk:pojk:2019:10", "status", "repealed", "")

    assert actions.calls == []


def test_every_action_needs_a_reason_a_reviewer_can_read_later(actions) -> None:
    with pytest.raises(InvalidCorrection, match="reason"):
        Curate(actions).suppress(ANI, "ojk:pojk:2025:25", "  ")


def test_an_assigned_id_is_normalised_and_checked(actions) -> None:
    Curate(actions).assign_id(ANI, "unresolved:ojk:0f2aa739", " OJK:POJK:2014:6 ", "Header reads 6/POJK.05/2014")

    assert actions.calls[0][3] == {"document_id": "ojk:pojk:2014:6"}


def test_a_review_item_is_resolved_or_dismissed_only(actions) -> None:
    Curate(actions).decide_review(ANI, 12, "dismissed", "The text is a web page; OJK M3 will bring the PDF")

    with pytest.raises(InvalidCorrection):
        Curate(actions).decide_review(ANI, 12, "deleted", "x")
    assert [c[1] for c in actions.calls] == ["decide_review"]


def test_a_conflict_keeps_the_correction_or_accepts_the_source(actions) -> None:
    curate = Curate(actions)

    curate.resolve_conflict(ANI, 4, "keep", "Kurator benar; sumber salah ketik")
    curate.resolve_conflict(ANI, 5, "accept", "Sumber sudah memperbaiki")

    assert [c[3] for c in actions.calls] == [{"state": "kept_override"}, {"state": "accepted_source"}]


def test_a_citation_is_linked_to_a_canonical_document(actions) -> None:
    Curate(actions).link_citation(ANI, 88, "id:uu:2011:21", "Mengingat angka 1")

    assert actions.calls[0][1:4] == ("link_citation", {"citation_id": 88}, {"to_document": "id:uu:2011:21"})
