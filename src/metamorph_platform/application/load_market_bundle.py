"""Load one market connector's bundle (a full snapshot, or whole datasets) into the market store.

The loader's guarantees are contract v2's (load_bundle.py): a run is loaded once, a record the contract rejects
is quarantined for review, an unchanged record is skipped by its package hash, each record is saved whole or
not at all, and a record the snapshot no longer has is marked missing. A bundle of whole datasets (snapshot
"datasets") can only make series of the datasets it carries go missing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_market import Bundle, BundleEntry, SeriesRecord, Snapshot

from metamorph_platform.application.ports import BlobStore, IngestLedger, MarketStore, ReviewQueue
from metamorph_platform.domain.loading import ReviewKind, SaveOutcome
from metamorph_platform.domain.market import market_package_hash, unknown_scope_problems


@dataclass
class MarketLoadReport:
    bundle_id: int
    connector: str
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    quarantined: int = 0
    missing: int = 0  # records this connector no longer sends

    def counts(self) -> dict[str, int]:
        return {key: value for key, value in asdict(self).items() if isinstance(value, int) and key != "bundle_id"}


class LoadMarketBundle:
    def __init__(self, ledger: IngestLedger, market: MarketStore, blobs: BlobStore, reviews: ReviewQueue) -> None:
        self.ledger = ledger
        self.market = market
        self.blobs = blobs
        self.reviews = reviews

    def run(self, bundle: Bundle, uri: str) -> MarketLoadReport:
        bundle_id = self.ledger.start_bundle(bundle.manifest, uri)
        report = MarketLoadReport(bundle_id=bundle_id, connector=bundle.manifest.connector)
        known, present = (self.market.registers(), self.market.sources()), set()
        within = None if bundle.manifest.snapshot == Snapshot.FULL else set()
        try:
            for entry in bundle.entries():
                if within is not None and isinstance(entry.record, SeriesRecord):
                    within.add(entry.record.series.dataset)
                self._load(entry, bundle, known, report, present)
            report.missing = self.market.mark_missing(report.connector, present, within)
        except Exception as error:
            self.ledger.fail_bundle(bundle_id, repr(error))
            raise
        self.ledger.finish_bundle(bundle_id, report.counts())
        return report

    def _load(
        self,
        entry: BundleEntry,
        bundle: Bundle,
        known: tuple[set[str], set[str]],
        report: MarketLoadReport,
        present: set[str],
    ) -> None:
        record = entry.record
        if record is not None:
            present.add(record.source.source_id)  # it exists at the source, even if its line is rejected
        problems = entry.problems + (unknown_scope_problems(record, *known) if record else [])
        if record is None or problems:
            self._quarantine(entry, problems, report)
            return
        connector, source_id = record.source.connector, record.source.source_id
        fingerprint = market_package_hash(record)
        if self.market.package_hash(connector, source_id) == fingerprint:
            self.market.seen_again(connector, source_id, report.bundle_id)
            report.unchanged += 1
            return
        files = {
            file.sha256: self.blobs.store(file.sha256, bundle.blob_path(file.sha256), file.media_type)
            for file in record.files
        }
        outcome = self.market.save(record, bundle_id=report.bundle_id, package_hash=fingerprint, files=files)
        report.new += outcome is SaveOutcome.NEW
        report.changed += outcome is SaveOutcome.CHANGED

    def _quarantine(self, entry: BundleEntry, problems: list[str], report: MarketLoadReport) -> None:
        source_id = entry.record.source.source_id if entry.record else None
        self.ledger.quarantine(report.bundle_id, entry.line, entry.raw, problems, source_id)
        self.reviews.ensure_open(ReviewKind.QUARANTINE, {"bundle_id": report.bundle_id, "line": entry.line})
        report.quarantined += 1
