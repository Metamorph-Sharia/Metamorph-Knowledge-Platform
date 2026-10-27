"""Is ingestion healthy? The rules, given what the database knows about each connector's loads.

    a connector     ok while it loaded within 1.5 × its cadence; warning after that, or when a run failed
                    since its last good load; critical after 3 × its cadence, or if it never loaded
    quarantine      warning while lines that broke the contract wait for a person
    a register      warning while its newest published edition is older than the register's bound, or it has none
                    (market.register.fresh_days: OJK publishes each list one to three months after its date)

The overall status is the worst check's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

LATE = 1.5  # × the cadence: one run missed
SILENT = 3.0  # × the cadence: something is broken

# How often each connector is scheduled to load (dags/metamorph_pipeline/jobs.py).
CADENCE = {
    "ojk": timedelta(days=1),
    "bpk": timedelta(days=1),
    "bi-website": timedelta(days=1),
    "dsn-fatwa": timedelta(days=7),
    "ojk-register": timedelta(days=7),
}


class Severity(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


@dataclass(frozen=True)
class ConnectorActivity:
    connector: str
    last_loaded_at: datetime | None
    last_failed_at: datetime | None = None


@dataclass(frozen=True)
class RegisterFreshness:
    register: str
    newest_edition: date | None
    fresh_days: int


@dataclass(frozen=True)
class HealthFacts:
    now: datetime
    connectors: tuple[ConnectorActivity, ...]
    open_reviews: Mapping[str, int]  # review kind → open items
    registers: tuple[RegisterFreshness, ...] = ()


@dataclass(frozen=True)
class Check:
    name: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class Health:
    status: Severity
    checks: tuple[Check, ...]


def assess(facts: HealthFacts, cadence: Mapping[str, timedelta] = CADENCE) -> Health:
    activity = {a.connector: a for a in facts.connectors}
    checks = [
        *(_connector(name, every, activity.get(name), facts.now) for name, every in cadence.items()),
        _quarantine(facts.open_reviews.get("quarantine", 0)),
        *(_register(register, facts.now.date()) for register in facts.registers),
    ]
    return Health(max((c.severity for c in checks), key=lambda s: s.rank), tuple(checks))


def _connector(name: str, every: timedelta, activity: ConnectorActivity | None, now: datetime) -> Check:
    if activity is None or activity.last_loaded_at is None:
        return Check(name, Severity.CRITICAL, "never loaded")
    age = now - activity.last_loaded_at
    detail = f"last loaded {_hours(age)} ago (every {_hours(every)})"
    if age > every * SILENT:
        return Check(name, Severity.CRITICAL, detail)
    if age > every * LATE:
        return Check(name, Severity.WARNING, detail)
    if activity.last_failed_at and activity.last_failed_at > activity.last_loaded_at:
        return Check(
            name, Severity.WARNING, f"{detail}; a later run failed {_hours(now - activity.last_failed_at)} ago"
        )
    return Check(name, Severity.OK, detail)


def _quarantine(waiting: int) -> Check:
    if waiting:
        return Check("quarantine", Severity.WARNING, f"{waiting} bundle line(s) broke the contract and wait for review")
    return Check("quarantine", Severity.OK, "nothing quarantined")


def _register(register: RegisterFreshness, today: date) -> Check:
    name = f"register {register.register}"
    if register.newest_edition is None:
        return Check(name, Severity.WARNING, "no edition published yet")
    age = (today - register.newest_edition).days
    detail = f"newest edition {register.newest_edition}, {age} days old (fresh within {register.fresh_days})"
    return Check(name, Severity.WARNING if age > register.fresh_days else Severity.OK, detail)


def _hours(span: timedelta) -> str:
    hours = span.total_seconds() / 3600
    return f"{hours:.0f} h" if hours >= 1 else "under 1 h"
