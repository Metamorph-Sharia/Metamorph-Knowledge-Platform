"""Assess ingestion health from what the database knows, and record the result (ingest.health_snapshot)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from metamorph_platform.application.ports import HealthLog
from metamorph_platform.domain.health import CADENCE, Health, assess


class CheckHealth:
    def __init__(self, log: HealthLog, cadence: Mapping[str, timedelta] = CADENCE) -> None:
        self.log = log
        self.cadence = cadence

    def run(self) -> Health:
        health = assess(self.log.facts(), self.cadence)
        self.log.record(health)
        return health
