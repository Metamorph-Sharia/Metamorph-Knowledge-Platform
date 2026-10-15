"""Turn open citations into links wherever their target is held (domain/resolution.py).

A citation whose target isn't held yet stays open and is tried again next run: it links as soon as the
target's connector loads it. One that names no document at all goes to a person. Links no citation
supports any more (their citations were replaced by a reload or a re-parse) are dropped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_platform.application.ports import CitationLinks, NewLink, OpenCitation, ReviewQueue
from metamorph_platform.domain.loading import ReviewKind
from metamorph_platform.domain.resolution import identifiable, resolve


@dataclass
class ResolveReport:
    linked: int = 0
    waiting: int = 0  # the target is named but not held yet
    unidentified: int = 0  # nothing names the target: queued for a person
    links_dropped: int = 0

    def counts(self) -> dict[str, int]:
        return asdict(self)


class ResolveCitations:
    def __init__(self, links: CitationLinks, reviews: ReviewQueue) -> None:
        self.links = links
        self.reviews = reviews

    def run(self) -> ResolveReport:
        report = ResolveReport(links_dropped=self.links.drop_unsupported_links())
        known, aliases = self.links.document_ids(), self.links.unambiguous_aliases()
        for citation in self.links.open_citations():
            resolution = resolve(citation.target_id, citation.target_text, known=known, aliases=aliases)
            if resolution and resolution.target_id != citation.document_id:
                self.links.link(citation.id, _link(citation, resolution.target_id, resolution.method))
                report.linked += 1
            elif identifiable(citation.target_id, citation.target_text):
                report.waiting += 1
            else:
                report.unidentified += 1
                subject = {"document_id": citation.document_id, "target_text": citation.target_text}
                self.reviews.ensure_open(ReviewKind.UNRESOLVED_CITATION, subject)
        return report


def _link(citation: OpenCitation, target_id: str, method: str) -> NewLink:
    return NewLink(
        type=citation.relation,
        from_document=citation.document_id,
        from_address=citation.from_address,
        to_document=target_id,
        to_address=citation.to_address,
        method=method,
        confidence=citation.confidence,
    )
