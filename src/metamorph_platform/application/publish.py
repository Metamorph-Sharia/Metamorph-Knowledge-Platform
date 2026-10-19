"""Refresh `published`, the read contract of the Knowledge and Retrieval layer, for what changed.

Only a document that passes the publish gate is written (domain/gate.py). One that fails is held: the
version published before, if any, stays as it was, and the reasons go to the held list.
Provisions are published with their text, cut from the text they belong to; each such text is read once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_platform.application.ports import BlobReader, HoldList, PublicationSource, PublishedStore
from metamorph_platform.domain.publishing import (
    DocumentSnapshot,
    effective_texts,
    hold_reasons_of,
    must_be_removed,
    publication_of,
)
from metamorph_platform.domain.structure import PARSER_VERSION


@dataclass
class PublishReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    held: int = 0  # failed the gate: kept at the version published before, or not published at all

    def counts(self) -> dict[str, int]:
        return asdict(self)


class Publish:
    def __init__(
        self,
        source: PublicationSource,
        published: PublishedStore,
        texts: BlobReader,
        *,
        holds: HoldList,
        parser_version: str = PARSER_VERSION,
    ) -> None:
        self.source = source
        self.published = published
        self.texts = texts
        self.holds = holds
        self.parser_version = parser_version

    def run(self, *, everything: bool = False) -> PublishReport:
        report = PublishReport()
        for document_id in self.source.documents_to_publish(everything):
            snapshot = self.source.snapshot(document_id)
            if snapshot is None or must_be_removed(snapshot):
                report.removed += self.published.remove(document_id)
                self.holds.clear(document_id)
            elif reasons := hold_reasons_of(snapshot, self.parser_version):
                self.holds.record(document_id, reasons)
                report.held += 1
            else:
                self.holds.clear(document_id)
                if self.published.replace(publication_of(snapshot, self._texts_of(snapshot))):
                    report.added += 1
                else:
                    report.updated += 1
        return report

    def _texts_of(self, snapshot: DocumentSnapshot) -> dict[str, str]:
        wanted = {provision.text_sha256 for provision in snapshot.provisions}
        return {
            text.sha256: self.texts.read(text.storage_key).decode("utf-8")
            for text in effective_texts(snapshot.texts, snapshot.corrections)
            if text.sha256 in wanted
        }
