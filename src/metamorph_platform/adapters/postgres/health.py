"""PostgreSQL side of health: facts from ingest and curation, snapshots into ingest.health_snapshot."""

from __future__ import annotations

import json
from dataclasses import asdict

import psycopg

from metamorph_platform.domain.health import (
    ConnectorActivity,
    Health,
    HealthFacts,
    RegisterFreshness,
    StatisticsFreshness,
)

_ACTIVITY = """
SELECT connector,
       max(loaded_at) FILTER (WHERE state = 'loaded'),
       max(received_at) FILTER (WHERE state = 'failed')
FROM ingest.bundle GROUP BY connector ORDER BY connector
"""
_OPEN_REVIEWS = "SELECT kind, count(*) FROM curation.review_item WHERE state = 'open' GROUP BY kind"


class PostgresHealth:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def facts(self) -> HealthFacts:
        (now,) = self.connection.execute("SELECT now()").fetchone()
        return HealthFacts(
            now=now,
            connectors=tuple(ConnectorActivity(*row) for row in self.connection.execute(_ACTIVITY)),
            open_reviews=dict(self.connection.execute(_OPEN_REVIEWS).fetchall()),
            registers=tuple(RegisterFreshness(*row) for row in self.connection.execute(_REGISTERS)),
            statistics=tuple(StatisticsFreshness(*row) for row in self.connection.execute(_STATISTICS)),
        )

    def record(self, health: Health) -> None:
        self.connection.execute(
            "INSERT INTO ingest.health_snapshot (status, checks) VALUES (%s, %s)",
            (health.status.value, json.dumps([asdict(check) for check in health.checks])),
        )

# A register's newest edition as published; one without a publish yet has none.
_REGISTERS = """
SELECT r.id, p.newest_edition, r.fresh_days
FROM market.register r LEFT JOIN published_market.register p ON p.id = r.id
ORDER BY r.id
"""

# The last day of a statistics source's newest published period, by each series' frequency; none before a publish.
_STATISTICS = """
SELECT s.id,
       max(p.last_period + CASE p.frequency WHEN 'quarterly' THEN interval '3 months'
                                            WHEN 'semiannual' THEN interval '6 months'
                                            WHEN 'annual' THEN interval '1 year'
                                            ELSE interval '1 month' END - interval '1 day')::date,
       s.fresh_days
FROM market.statistics_source s
LEFT JOIN published_market.dataset d ON d.source = s.id
LEFT JOIN published_market.series p ON p.dataset = d.id
GROUP BY s.id, s.fresh_days
ORDER BY s.id
"""
