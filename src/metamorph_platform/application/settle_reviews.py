"""Settle the review items whose cause went away by itself; leave the rest for the Metamorph team.

It runs in the build after parse and resolve, so each item is judged against today's texts and links
(domain/reviews.py). What it leaves open is what needs a person, counted by kind in its report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from metamorph_platform.application.ports import OpenReview, OpenReviews
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.reviews import citation_settlement, identity_settlement, structure_settlement
from metamorph_platform.domain.structure import PARSER_VERSION

ABOUT_A_DOCUMENT = {ReviewKind.STRUCTURE_SUSPECT, ReviewKind.UNRESOLVED_CITATION}


@dataclass
class SettleReport:
    settled: Counter[str] = field(default_factory=Counter)
    needs_a_person: Counter[str] = field(default_factory=Counter)

    def counts(self) -> dict[str, dict[str, int]]:
        return {"settled": dict(self.settled), "needs_a_person": dict(self.needs_a_person)}


class SettleReviews:
    def __init__(self, reviews: OpenReviews, *, parser_version: str = PARSER_VERSION) -> None:
        self.reviews = reviews
        self.parser_version = parser_version

    def run(self) -> SettleReport:
        report = SettleReport()
        for item in self.reviews.open_items():
            reason = self._settlement(item)
            if reason:
                self.reviews.settle(item.id, reason)
                report.settled[item.kind.value] += 1
            else:
                report.needs_a_person[item.kind.value] += 1
        return report

    def _settlement(self, item: OpenReview) -> str | None:
        subject = item.subject
        if item.kind is ReviewKind.UNRESOLVED_ID:
            return identity_settlement(document_exists=self.reviews.document_exists(subject["document_id"]))
        if item.kind in ABOUT_A_DOCUMENT and not self.reviews.document_exists(subject["document_id"]):
            return None  # renamed by a curator since: its evidence is filed under the new ID
        if item.kind is ReviewKind.STRUCTURE_SUSPECT:
            standing = self.reviews.text_standing(subject["document_id"], subject["text_sha256"])
            return structure_settlement(standing, subject.get("problems", []), self.parser_version)
        if item.kind is ReviewKind.UNRESOLVED_CITATION:
            unlinked = self.reviews.still_unlinked(subject["document_id"], subject["target_text"])
            return citation_settlement(still_unlinked=unlinked)
        return None  # a conflict, or a quarantined line: always a person's call
