"""The Metamorph team's corrections, as overlays: source records are never edited.

Each action is checked here (domain/curation.py) before anything is written, needs a reason a reviewer
can read later, and is audited by the CurationActions port in the same transaction as the change.
"""

from __future__ import annotations

from metamorph_platform.application.ports import CurationActions, Curator
from metamorph_platform.domain.curation import InvalidCorrection, parse_correction, validate_assigned_id

REVIEW_DECISIONS = ("resolved", "dismissed")
CONFLICT_DECISIONS = {"keep": "kept_override", "accept": "accepted_source"}


class Curate:
    def __init__(self, actions: CurationActions) -> None:
        self.actions = actions

    def correct(self, curator: Curator, document_id: str, field: str, raw_value: str, reason: str) -> None:
        value = parse_correction(field, raw_value)
        self.actions.correct(curator, document_id, field, value, _reason(reason))

    def withdraw_correction(self, curator: Curator, document_id: str, field: str, reason: str) -> None:
        self.actions.withdraw_correction(curator, document_id, field, _reason(reason))

    def suppress(self, curator: Curator, document_id: str, reason: str) -> None:
        self.actions.suppress(curator, document_id, _reason(reason))

    def restore(self, curator: Curator, document_id: str, reason: str) -> None:
        self.actions.restore(curator, document_id, _reason(reason))

    def decide_review(self, curator: Curator, item_id: int, state: str, note: str) -> None:
        if state not in REVIEW_DECISIONS:
            raise InvalidCorrection(f"a review item is {' or '.join(REVIEW_DECISIONS)}, not {state!r}")
        self.actions.decide_review(curator, item_id, state, _reason(note))

    def assign_id(self, curator: Curator, document_id: str, raw_id: str, reason: str) -> None:
        self.actions.assign_id(curator, document_id, validate_assigned_id(raw_id), _reason(reason))

    def link_citation(self, curator: Curator, citation_id: int, raw_target: str, reason: str) -> None:
        self.actions.link_citation(curator, citation_id, validate_assigned_id(raw_target), _reason(reason))

    def resolve_conflict(self, curator: Curator, conflict_id: int, decision: str, note: str) -> None:
        if decision not in CONFLICT_DECISIONS:
            raise InvalidCorrection("keep the correction or accept the source's value")
        self.actions.resolve_conflict(curator, conflict_id, CONFLICT_DECISIONS[decision], _reason(note))


def _reason(text: str) -> str:
    reason = " ".join(text.split())
    if not reason:
        raise InvalidCorrection("add a reason: the next reviewer will read it in the audit log")
    return reason
