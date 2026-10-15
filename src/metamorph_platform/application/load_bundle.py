"""Load one connector bundle (a full snapshot) into the registry.

Curation applies here too: a record a curator identified loads under the assigned ID, and a source that
changes a field a curator corrected raises a conflict instead of silently disagreeing with the correction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from metamorph_contract import Bundle, BundleEntry

from metamorph_platform.application.ports import BlobStore, IngestLedger, Overrides, Registry, ReviewQueue
from metamorph_platform.domain.curation import conflicts, source_values, with_assigned_id
from metamorph_platform.domain.loading import (
    ReviewKind,
    SaveOutcome,
    blobs_needed,
    needs_identity_review,
    package_hash,
)


@dataclass
class LoadReport:
    bundle_id: int
    connector: str
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    quarantined: int = 0
    missing: int = 0  # records this connector no longer lists
    to_review: int = 0  # documents waiting for a person to identify them
    changed_documents: set[str] = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        return {key: value for key, value in asdict(self).items() if isinstance(value, int) and key != "bundle_id"}


class LoadBundle:
    """Valid lines become registry records; invalid ones are quarantined; nothing is half-loaded.

    Every document is checked again on each load, unchanged or not, so a review item lost to a crash
    is reopened next time.
    """

    def __init__(
        self, ledger: IngestLedger, registry: Registry, blobs: BlobStore, reviews: ReviewQueue, overrides: Overrides
    ) -> None:
        self.ledger = ledger
        self.registry = registry
        self.blobs = blobs
        self.reviews = reviews
        self.overrides = overrides

    def run(self, bundle: Bundle, uri: str, *, full_snapshot: bool = True) -> LoadReport:
        """`full_snapshot=False`: the bundle adds documents (a curator's upload); absence means nothing."""
        bundle_id = self.ledger.start_bundle(bundle.manifest, uri)
        report = LoadReport(bundle_id=bundle_id, connector=bundle.manifest.connector)
        present: set[str] = set()
        try:
            for entry in bundle.entries():
                self._load(entry, bundle, report, present)
            if full_snapshot:
                report.missing = self.registry.mark_missing(report.connector, present)
        except Exception as error:
            self.ledger.fail_bundle(bundle_id, repr(error))
            raise
        self.ledger.finish_bundle(bundle_id, report.counts())
        return report

    def _load(self, entry: BundleEntry, bundle: Bundle, report: LoadReport, present: set[str]) -> None:
        if entry.document is not None:
            present.add(entry.document.source.source_id)  # it exists at the source, even if its line is broken
        if not entry.is_valid:
            self._quarantine(entry, report)
            return
        received = entry.document
        connector, source_id = received.source.connector, received.source.source_id
        fingerprint = package_hash(received)  # of what the source sent, so a source change is still seen
        assigned = self.registry.assigned_id(connector, source_id)
        document = with_assigned_id(received, assigned) if assigned else received
        if self.registry.package_hash(connector, source_id) == fingerprint:
            self.registry.seen_again(connector, source_id, report.bundle_id)
            report.unchanged += 1
        else:
            stored = {
                need.sha256: self.blobs.store(need.sha256, bundle.blob_path(need.sha256), need.media_type)
                for need in blobs_needed(document)
            }
            outcome = self.registry.save(document, bundle_id=report.bundle_id, package_hash=fingerprint, blobs=stored)
            report.new += outcome is SaveOutcome.NEW
            report.changed += outcome is SaveOutcome.CHANGED
            report.changed_documents.add(document.document.id)
            self._check_corrections(document)
        if needs_identity_review(document):
            self.reviews.ensure_open(ReviewKind.UNRESOLVED_ID, {"document_id": document.document.id})
            report.to_review += 1

    def _check_corrections(self, document) -> None:
        overrides = self.overrides.active(document.document.id)
        for override, source_value in conflicts(overrides, source_values(document)):
            self.overrides.raise_conflict(override.id, source_value)
            self.reviews.ensure_open(ReviewKind.CONFLICT, {"override_id": override.id})

    def _quarantine(self, entry: BundleEntry, report: LoadReport) -> None:
        source_id = entry.document.source.source_id if entry.document else None
        self.ledger.quarantine(report.bundle_id, entry.line, entry.raw, entry.problems, source_id)
        self.reviews.ensure_open(ReviewKind.QUARANTINE, {"bundle_id": report.bundle_id, "line": entry.line})
        report.quarantined += 1
