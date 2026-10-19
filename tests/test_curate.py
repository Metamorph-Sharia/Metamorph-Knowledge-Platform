"""The curation actions against in-memory ports: validation, and what each records in the audit log."""

from __future__ import annotations

import hashlib

import pytest
from fakes import MemoryBlobStore, MemoryCorrectableTexts, MemoryCurationActions
from metamorph_contract import join_pages

from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.ports import CorrectableText, CurationRefused, Curator
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


def test_a_text_is_approved_as_it_is_with_a_reason(actions) -> None:
    Curate(actions).approve(ANI, "ojk:pojk:2019:10", "a" * 64, "  Pasal 3 dicabut oleh POJK 12/2021 ")

    assert actions.calls == [
        (ANI, "approve", {"document_id": "ojk:pojk:2019:10", "text_sha256": "a" * 64}, None,
         "Pasal 3 dicabut oleh POJK 12/2021"),
    ]  # fmt: skip


def test_an_approval_is_withdrawn_with_a_reason(actions) -> None:
    with pytest.raises(InvalidCorrection, match="reason"):
        Curate(actions).withdraw_approval(ANI, "ojk:pojk:2019:10", "a" * 64, "")

    Curate(actions).withdraw_approval(ANI, "ojk:pojk:2019:10", "a" * 64, "Pasal 3 ternyata ada di PDF")

    assert [call[1] for call in actions.calls] == ["withdraw_approval"]


SOURCE_TEXT = join_pages(["PERATURAN OTORITAS JASA KEUANGAN", "Pasal 1\nSatu.\nPasal 3\nTiga."])
SOURCE_SHA = hashlib.sha256(SOURCE_TEXT.encode()).hexdigest()


@pytest.fixture
def texts() -> tuple[MemoryCorrectableTexts, MemoryBlobStore]:
    blobs = MemoryBlobStore()
    blobs.put(SOURCE_SHA, SOURCE_TEXT.encode(), "text/markdown")
    correctable = MemoryCorrectableTexts({("ojk:pojk:2019:10", SOURCE_SHA): CorrectableText(f"x/{SOURCE_SHA}", True)})
    return correctable, blobs


def test_a_corrected_text_is_checked_stored_then_recorded(actions, texts) -> None:
    correctable, blobs = texts
    fixed = SOURCE_TEXT.replace("Pasal 3", "Pasal 2\nDua.\nPasal 3")

    CorrectText(actions, correctable, blobs, blobs).correct(ANI, "ojk:pojk:2019:10", SOURCE_SHA, fixed, " PDF hal. 2 ")

    stored_sha = hashlib.sha256((fixed + "\n").encode()).hexdigest()
    assert blobs.blobs[stored_sha] == (fixed + "\n").encode()
    assert actions.calls == [
        (ANI, "correct_text", {"document_id": "ojk:pojk:2019:10", "text_sha256": SOURCE_SHA},
         {"sha256": stored_sha, "storage_key": f"blobs/{stored_sha[:2]}/{stored_sha}"}, "PDF hal. 2"),
    ]  # fmt: skip


def test_a_correction_that_breaks_the_page_markers_writes_nothing(actions, texts) -> None:
    correctable, blobs = texts
    broken = SOURCE_TEXT.replace("<!-- page 2 -->\n", "")

    with pytest.raises(InvalidCorrection, match="page 2"):
        CorrectText(actions, correctable, blobs, blobs).correct(ANI, "ojk:pojk:2019:10", SOURCE_SHA, broken, "x")

    assert actions.calls == [] and len(blobs.blobs) == 1


def test_only_a_current_main_text_can_be_corrected_and_only_with_a_reason(actions, texts) -> None:
    correctable, blobs = texts
    correct = CorrectText(actions, correctable, blobs, blobs).correct

    with pytest.raises(CurationRefused, match="current main text"):
        correct(ANI, "ojk:pojk:2019:10", "f" * 64, "Pasal 1", "x")
    with pytest.raises(InvalidCorrection, match="reason"):
        correct(ANI, "ojk:pojk:2019:10", SOURCE_SHA, "Pasal 1", "")


def test_a_text_correction_is_withdrawn_with_a_reason(actions, texts) -> None:
    correctable, blobs = texts

    CorrectText(actions, correctable, blobs, blobs).withdraw(ANI, "ojk:pojk:2019:10", SOURCE_SHA, "Sumber sudah benar")

    assert [call[1] for call in actions.calls] == ["withdraw_text_correction"]
