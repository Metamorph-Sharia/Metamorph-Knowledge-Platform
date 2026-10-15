"""Rebuild what links say about validity: status events and the date an article's wording stopped applying."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from metamorph_platform.application.ports import Validity
from metamorph_platform.domain.validity import provision_expiries, status_changes


@dataclass
class ValidityReport:
    status_changes: int = 0
    expiries: int = 0
    documents_changed: int = 0

    def counts(self) -> dict[str, int]:
        return asdict(self)


class ComputeValidity:
    def __init__(self, store: Validity) -> None:
        self.store = store

    def run(self) -> ValidityReport:
        links = self.store.dated_links()
        changes, expiries = status_changes(links), provision_expiries(links)
        return ValidityReport(len(changes), len(expiries), self.store.apply(changes, expiries))
