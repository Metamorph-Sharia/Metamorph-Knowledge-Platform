"""The Metamorph team's corrections, as overlays: source records are never edited.

Each action is checked here (domain/curation.py) before anything is written, needs a reason a reviewer
can read later, and is audited by the CurationActions port in the same transaction as the change.
"""

from __future__ import annotations

import hashlib

from metamorph_platform.application.ports import (
    BlobReader,
    BlobStore,
    CorrectableTexts,
    CurationActions,
    CurationRefused,
    Curator,
)
from metamorph_platform.domain.curation import (
    InvalidCorrection,
    checked_reason,
    checked_text_correction,
    parse_correction,
    validate_assigned_id,
)
from metamorph_platform.domain.loading import TEXT_MEDIA_TYPE

REVIEW_DECISIONS = ("resolved", "dismissed")
CONFLICT_DECISIONS = {"keep": "kept_override", "accept": "accepted_source"}


class Curate:
    def __init__(self, actions: CurationActions) -> None:
        self.actions = actions

    def correct(self, curator: Curator, document_id: str, field: str, raw_value: str, reason: str) -> None:
        value = parse_correction(field, raw_value)
        self.actions.correct(curator, document_id, field, value, checked_reason(reason))

    def withdraw_correction(self, curator: Curator, document_id: str, field: str, reason: str) -> None:
        self.actions.withdraw_correction(curator, document_id, field, checked_reason(reason))

    def approve(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        """Publish the text with the structure problems it has now: the gaps are genuine (domain/gate.py)."""
        self.actions.approve(curator, document_id, text_sha256, checked_reason(reason))

    def withdraw_approval(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        self.actions.withdraw_approval(curator, document_id, text_sha256, checked_reason(reason))

    def suppress(self, curator: Curator, document_id: str, reason: str) -> None:
        self.actions.suppress(curator, document_id, checked_reason(reason))

    def restore(self, curator: Curator, document_id: str, reason: str) -> None:
        self.actions.restore(curator, document_id, checked_reason(reason))

    def decide_review(self, curator: Curator, item_id: int, state: str, note: str) -> None:
        if state not in REVIEW_DECISIONS:
            raise InvalidCorrection(f"a review item is {' or '.join(REVIEW_DECISIONS)}, not {state!r}")
        self.actions.decide_review(curator, item_id, state, checked_reason(note))

    def assign_id(self, curator: Curator, document_id: str, raw_id: str, reason: str) -> None:
        self.actions.assign_id(curator, document_id, validate_assigned_id(raw_id), checked_reason(reason))

    def link_citation(self, curator: Curator, citation_id: int, raw_target: str, reason: str) -> None:
        self.actions.link_citation(curator, citation_id, validate_assigned_id(raw_target), checked_reason(reason))

    def resolve_conflict(self, curator: Curator, conflict_id: int, decision: str, note: str) -> None:
        if decision not in CONFLICT_DECISIONS:
            raise InvalidCorrection("keep the correction or accept the source's value")
        self.actions.resolve_conflict(curator, conflict_id, CONFLICT_DECISIONS[decision], checked_reason(note))


class CorrectText:
    """A curator's corrected wording of a current main text: checked against the wording it replaces, stored
    beside the source's (which is never edited), then recorded as the text's correction."""

    def __init__(self, actions: CurationActions, texts: CorrectableTexts, blobs: BlobStore, reader: BlobReader) -> None:
        self.actions = actions
        self.texts = texts
        self.blobs = blobs
        self.reader = reader

    def correct(self, curator: Curator, document_id: str, text_sha256: str, wording: str, reason: str) -> None:
        reason = checked_reason(reason)
        current = self.texts.effective(document_id, text_sha256)
        if current is None:
            raise CurationRefused(f"{text_sha256[:12]} isn't a current main text of {document_id}")
        before = self.reader.read(current.storage_key).decode("utf-8")
        data = checked_text_correction(before, wording, paged=current.paged).encode("utf-8")
        stored = self.blobs.put(hashlib.sha256(data).hexdigest(), data, TEXT_MEDIA_TYPE)
        self.actions.correct_text(curator, document_id, text_sha256, stored.sha256, stored.storage_key, reason)

    def withdraw(self, curator: Curator, document_id: str, text_sha256: str, reason: str) -> None:
        self.actions.withdraw_text_correction(curator, document_id, text_sha256, checked_reason(reason))

