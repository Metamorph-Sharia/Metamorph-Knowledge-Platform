"""PostgreSQL side of health: facts from ingest and curation, snapshots into ingest.health_snapshot."""

from __future__ import annotations

import json
from dataclasses import asdict

import psycopg

from metamorph_platform.domain.health import ConnectorActivity, Health, HealthFacts

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
        )

    def record(self, health: Health) -> None:
        self.connection.execute(
            "INSERT INTO ingest.health_snapshot (status, checks) VALUES (%s, %s)",
            (health.status.value, json.dumps([asdict(check) for check in health.checks])),
        )
