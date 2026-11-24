"""Is ingestion healthy? The rules, given what the database knows about each connector's loads.

    a connector     ok while it loaded within 1.5 × its cadence; warning after that, or when a run failed
                    since its last good load; critical after 3 × its cadence, or if it never loaded.
                    A connector that loads every weekday has a `Weekdays` cadence: Saturdays and Sundays (UTC)
                    do not count, so a dead host warns after a weekday and a half, not four and a half days
    quarantine      warning while lines that broke the contract wait for a person
    a register      warning while its newest published edition is older than the register's bound, or it has none
                    (market.register.fresh_days: OJK publishes each list one to three months after its date)
    statistics      warning while a source's newest published month ended longer ago than its bound, or it has none
                    (market.statistics_source.fresh_days: OJK's portal shows a month about two months after it ends)

The overall status is the worst check's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

LATE = 1.5  # × the cadence: one run missed
SILENT = 3.0  # × the cadence: something is broken


class Weekdays(timedelta):
    """A cadence counted in weekdays: the time a load is overdue leaves out the weekend."""


# How often each connector is scheduled to load (dags/metamorph_pipeline/jobs.py). The daily jobs run on weekdays, on
# the collection host (docs/adr/0001-collection-on-a-residential-host.md).
EVERY_WEEKDAY = Weekdays(days=1)
CADENCE = {
    "ojk": EVERY_WEEKDAY,
    "bpk": EVERY_WEEKDAY,
    "bi-website": EVERY_WEEKDAY,
    "dsn-fatwa": timedelta(days=7),
    "ojk-register": timedelta(days=7),
    "ojk-stats": timedelta(days=7),
    "bi-stats": timedelta(days=7),
    "bps-stats": timedelta(days=7),
    "reports": timedelta(days=7),  # regulators' reports: LPKSI synced weekly, the rest imported from the inbox
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
class StatisticsFreshness:
    source: str
    newest_end: date | None  # the last day of its newest published period, whatever its frequency
    fresh_days: int


@dataclass(frozen=True)
class HealthFacts:
    now: datetime
    connectors: tuple[ConnectorActivity, ...]
    open_reviews: Mapping[str, int]  # review kind → open items
    registers: tuple[RegisterFreshness, ...] = ()
    statistics: tuple[StatisticsFreshness, ...] = ()


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
        *(_statistics(source, facts.now.date()) for source in facts.statistics),
    ]
    return Health(max((c.severity for c in checks), key=lambda s: s.rank), tuple(checks))


def _connector(name: str, every: timedelta, activity: ConnectorActivity | None, now: datetime) -> Check:
    if activity is None or activity.last_loaded_at is None:
        return Check(name, Severity.CRITICAL, "never loaded")
    since = activity.last_loaded_at
    age = _without_weekends(since, now) if isinstance(every, Weekdays) else now - since
    weekends = ", weekends not counted" if isinstance(every, Weekdays) else ""
    detail = f"last loaded {_hours(now - since)} ago (every {_hours(every)}{weekends})"
    if age > every * SILENT:
        return Check(name, Severity.CRITICAL, detail)
    if age > every * LATE:
        return Check(name, Severity.WARNING, detail)
    if activity.last_failed_at and activity.last_failed_at > activity.last_loaded_at:
        return Check(
            name, Severity.WARNING, f"{detail}; a later run failed {_hours(now - activity.last_failed_at)} ago"
        )
    return Check(name, Severity.OK, detail)


def _without_weekends(since: datetime, now: datetime) -> timedelta:
    """The time from `since` to `now`, less the Saturdays and Sundays (UTC) in it."""
    age = now - since
    day = since.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < now:
        if day.weekday() >= 5:
            age -= min(day + timedelta(days=1), now) - max(day, since)
        day += timedelta(days=1)
    return age


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


def _statistics(source: StatisticsFreshness, today: date) -> Check:
    name = f"statistics {source.source}"
    if source.newest_end is None:
        return Check(name, Severity.WARNING, "no period published yet")
    age = (today - source.newest_end).days
    detail = f"newest period ended {source.newest_end:%Y-%m-%d}, {age} days ago (fresh within {source.fresh_days})"
    return Check(name, Severity.WARNING if age > source.fresh_days else Severity.OK, detail)


def _hours(span: timedelta) -> str:
    hours = span.total_seconds() / 3600
    return f"{hours:.0f} h" if hours >= 1 else "under 1 h"
