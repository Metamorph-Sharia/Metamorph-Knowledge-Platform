"""Settle the citation items whose cause went away by itself; leave the rest for the Metamorph team.

It runs in the build after parse and resolve, so each item is judged against today's citations and links
(domain/reviews.py). What it leaves open is what needs a person, counted by kind in its report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from metamorph_platform.application.ports import OpenReview, OpenReviews
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.resolution import named_targets
from metamorph_platform.domain.reviews import citation_settlement


@dataclass
class SettleReport:
    settled: Counter[str] = field(default_factory=Counter)
    needs_a_person: Counter[str] = field(default_factory=Counter)

    def counts(self) -> dict[str, dict[str, int]]:
        return {"settled": dict(self.settled), "needs_a_person": dict(self.needs_a_person)}


class SettleReviews:
    def __init__(self, reviews: OpenReviews) -> None:
        self.reviews = reviews

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
        if item.kind is not ReviewKind.UNRESOLVED_CITATION:
            return None  # a conflict, or a quarantined line: always a person's call
        document_id, target_text = item.subject["document_id"], item.subject["target_text"]
        if not self.reviews.document_exists(document_id):
            return None  # renamed by a curator since: its evidence is filed under the new ID
        unlinked = self.reviews.still_unlinked(document_id, target_text)
        named = named_targets(None, target_text)
        return citation_settlement(still_unlinked=unlinked, named=named, citing=document_id)
