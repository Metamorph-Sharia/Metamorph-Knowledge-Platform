"""Refresh `published`, the read contract of the Knowledge and Retrieval layer, for what changed.

Provisions are published with their text, cut from the text they belong to; each such text is read once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_platform.application.ports import BlobReader, PublicationSource, PublishedStore
from metamorph_platform.domain.publishing import DocumentSnapshot, publication_of


@dataclass
class PublishReport:
    added: int = 0
    updated: int = 0
    removed: int = 0

    def counts(self) -> dict[str, int]:
        return asdict(self)


class Publish:
    def __init__(self, source: PublicationSource, published: PublishedStore, texts: BlobReader) -> None:
        self.source = source
        self.published = published
        self.texts = texts

    def run(self, *, everything: bool = False) -> PublishReport:
        report = PublishReport()
        for document_id in self.source.documents_to_publish(everything):
            snapshot = self.source.snapshot(document_id)
            publication = publication_of(snapshot, self._texts_of(snapshot)) if snapshot else None
            if publication is None:
                report.removed += self.published.remove(document_id)
            elif self.published.replace(publication):
                report.added += 1
            else:
                report.updated += 1
        return report

    def _texts_of(self, snapshot: DocumentSnapshot) -> dict[str, str]:
        wanted = {provision.text_sha256 for provision in snapshot.provisions}
        return {
            text.sha256: self.texts.read(text.storage_key).decode("utf-8")
            for text in snapshot.texts
            if text.sha256 in wanted
        }
