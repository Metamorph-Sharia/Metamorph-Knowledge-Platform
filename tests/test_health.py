"""Is ingestion healthy? Each connector loads on its cadence, its last run didn't fail, nothing is stuck."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fakes import MemoryHealth

from metamorph_platform.application.check_health import CheckHealth
from metamorph_platform.domain.health import ConnectorActivity, HealthFacts, Severity, assess

NOW = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
CADENCE = {"ojk": timedelta(days=1), "dsn-fatwa": timedelta(days=7)}


def facts(*activity: ConnectorActivity, open_reviews: dict[str, int] | None = None) -> HealthFacts:
    return HealthFacts(now=NOW, connectors=activity, open_reviews=open_reviews or {})


def loaded(connector: str, ago: timedelta, failed_ago: timedelta | None = None) -> ConnectorActivity:
    return ConnectorActivity(connector, NOW - ago, NOW - failed_ago if failed_ago else None)


def severities(health) -> dict[str, Severity]:
    return {check.name: check.severity for check in health.checks}


def test_connectors_loaded_on_their_cadence_are_healthy() -> None:
    health = assess(facts(loaded("ojk", timedelta(hours=20)), loaded("dsn-fatwa", timedelta(days=6))), CADENCE)

    assert health.status == Severity.OK
    assert severities(health) == {"ojk": Severity.OK, "dsn-fatwa": Severity.OK, "quarantine": Severity.OK}


def test_a_late_load_warns_and_a_long_silence_is_critical() -> None:
    health = assess(facts(loaded("ojk", timedelta(hours=40)), loaded("dsn-fatwa", timedelta(days=22))), CADENCE)

    assert severities(health)["ojk"] == Severity.WARNING
    assert severities(health)["dsn-fatwa"] == Severity.CRITICAL
    assert health.status == Severity.CRITICAL


def test_a_connector_that_never_loaded_is_critical() -> None:
    health = assess(facts(loaded("ojk", timedelta(hours=1))), CADENCE)

    assert severities(health)["dsn-fatwa"] == Severity.CRITICAL


def test_a_failed_run_after_the_last_good_load_warns() -> None:
    health = assess(facts(loaded("ojk", timedelta(hours=20), failed_ago=timedelta(hours=2)),
                          loaded("dsn-fatwa", timedelta(days=1))), CADENCE)  # fmt: skip

    assert severities(health)["ojk"] == Severity.WARNING
    assert "failed" in next(c.detail for c in health.checks if c.name == "ojk")


def test_quarantined_lines_waiting_for_a_person_warn() -> None:
    activity = (loaded("ojk", timedelta(hours=1)), loaded("dsn-fatwa", timedelta(days=1)))

    health = assess(facts(*activity, open_reviews={"quarantine": 3, "structure_suspect": 212}), CADENCE)

    assert severities(health)["quarantine"] == Severity.WARNING
    assert health.status == Severity.WARNING


def test_each_check_is_recorded() -> None:
    store = MemoryHealth(facts(loaded("ojk", timedelta(hours=1)), loaded("dsn-fatwa", timedelta(days=1))))

    health = CheckHealth(store, CADENCE).run()

    assert store.recorded == [health]
    assert health.status == Severity.OK


def test_health_exits_by_severity_unless_told_to_fail_only_on_worse() -> None:
    from metamorph_platform.cli import health_exit

    assert [health_exit(s, Severity.WARNING) for s in Severity] == [0, 1, 2]
    assert [health_exit(s, Severity.CRITICAL) for s in Severity] == [0, 0, 2]


def test_a_register_is_fresh_while_its_newest_edition_is_within_its_bound() -> None:
    from metamorph_platform.domain.health import RegisterFreshness

    fresh = RegisterFreshness("ojk:lpbbti", NOW.date() - timedelta(days=88), fresh_days=90)
    stale = RegisterFreshness("ojk:lpbbti", NOW.date() - timedelta(days=91), fresh_days=90)
    empty = RegisterFreshness("ojk:lpbbti", None, fresh_days=90)

    def check(register):  # noqa: ANN001, ANN202
        health = assess(HealthFacts(now=NOW, connectors=(), open_reviews={}, registers=(register,)), {})
        return next(found for found in health.checks if found.name == "register ojk:lpbbti")

    assert check(fresh).severity == Severity.OK
    assert check(fresh).detail == "newest edition 2026-07-24, 88 days old (fresh within 90)"
    assert check(stale).severity == Severity.WARNING
    assert (check(empty).severity, check(empty).detail) == (Severity.WARNING, "no edition published yet")
