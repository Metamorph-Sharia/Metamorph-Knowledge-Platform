"""Load every complete bundle a connector has left in the store and the ledger has not seen.

Collection uploads bundles; this runs on a schedule on the processing side. Per connector, oldest run first, so an
incremental bundle never lands out of order. A bundle that fails to load holds the connector's later bundles back
(the registry must not skip a step for a source); an incomplete one (an upload in progress, or abandoned) makes the
later ones wait. The next pass retries both: only a run the ledger has *loaded* is skipped, so a load that failed or
was killed part-way is started again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from metamorph_platform.application.ports import BundleSource, BundleStoreAuthenticationError, IngestLedger
from metamorph_platform.domain.bundle_locations import connector_of, run_location

LoadFromDirectory = Callable[[Path, str], object]  # (the bundle's directory, its URI): the layer's own loader


@dataclass
class PendingReport:
    loaded: int = 0
    skipped: int = 0  # the ledger has them already
    incomplete: int = 0  # no completion marker yet: an upload in progress, or one that was abandoned
    waiting: int = 0  # complete bundles behind an incomplete one
    held: int = 0  # the failed bundle and the complete ones behind it
    failed_run: str | None = None
    error: str | None = None


class LoadPendingBundles:
    def __init__(self, source: BundleSource, ledger: IngestLedger, load: LoadFromDirectory) -> None:
        self.source = source
        self.ledger = ledger
        self.load = load

    def run(self, connector_prefix: str) -> PendingReport:
        connector = connector_of(connector_prefix)
        report = PendingReport()
        for run_id in sorted(self.source.runs(connector_prefix)):
            location = run_location(connector_prefix, run_id)
            if self.ledger.already_loaded(connector, run_id):
                report.skipped += 1
            elif report.incomplete:
                report.waiting += 1
            elif not self.source.is_complete(location):
                report.incomplete += 1
            elif report.failed_run:
                report.held += 1
            else:
                self._load(location, run_id, report)
        return report

    def _load(self, location: str, run_id: str, report: PendingReport) -> None:
        try:
            with self.source.fetch(location) as directory:
                self.load(directory, location)
        except BundleStoreAuthenticationError:
            raise
        except Exception as error:
            report.held += 1
            report.failed_run, report.error = run_id, repr(error)
        else:
            report.loaded += 1
