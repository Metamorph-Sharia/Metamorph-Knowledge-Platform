"""Numbered plain-SQL migrations (`migrations/0001_name.sql`), applied in order, each exactly once.

An applied migration is never edited: its checksum is recorded, and a changed file stops the run.
Change the schema by adding the next number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
_FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_LOCK_KEY = 7_120_014  # pg_advisory_xact_lock key: two deploys never migrate at once

_BOOKKEEPING = """
CREATE SCHEMA IF NOT EXISTS platform_meta;
CREATE TABLE IF NOT EXISTS platform_meta.schema_migration (
    version    integer PRIMARY KEY,
    name       text NOT NULL,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str


def available(directory: Path = MIGRATIONS) -> list[Migration]:
    """The migration files, in order. Versions must run 1, 2, 3 … with no gap or repeat."""
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: expected NNNN_name.sql")
        migrations.append(Migration(int(match[1]), match[2], path.read_text(encoding="utf-8")))
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError(f"migration versions must be 1..{len(migrations)} without gaps, found {versions}")
    return migrations


def applied(connection: psycopg.Connection) -> list[AppliedMigration]:
    """Read-only: an empty database simply has nothing applied."""
    (table,) = connection.execute("SELECT to_regclass('platform_meta.schema_migration')").fetchone()
    if table is None:
        return []
    rows = connection.execute("SELECT version, name, checksum FROM platform_meta.schema_migration ORDER BY version")
    return [AppliedMigration(*row) for row in rows]


def migrate(connection: psycopg.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    """Apply what is pending, all in one transaction; returns what was applied."""
    migrations = available() if migrations is None else migrations
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        connection.execute(_BOOKKEEPING)
        done = {m.version: m for m in applied(connection)}
        _refuse_edited(migrations, done)
        pending = [m for m in migrations if m.version not in done]
        for migration in pending:
            connection.execute(migration.sql)
            connection.execute(
                "INSERT INTO platform_meta.schema_migration (version, name, checksum) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
    return pending


def _refuse_edited(migrations: list[Migration], done: dict[int, AppliedMigration]) -> None:
    edited = [m.name for m in migrations if m.version in done and done[m.version].checksum != m.checksum]
    if edited:
        raise MigrationError(f"already-applied migrations were edited: {edited}; add a new migration instead")
