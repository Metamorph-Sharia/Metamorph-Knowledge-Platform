"""`metamorph …`: the platform's command line, for people and for Airflow tasks.

Exit codes: 0 ok · 1 refused (e.g. an edited migration) · 2 misconfigured.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from metamorph_platform.adapters.postgres import migrate as migrations
from metamorph_platform.config import ConfigurationError, Settings

EXIT_OK, EXIT_REFUSED, EXIT_MISCONFIGURED = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        settings = Settings.from_environment()
        return arguments.run(settings)
    except ConfigurationError as error:
        print(f"configuration: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    except migrations.MigrationError as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metamorph", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True, metavar="COMMAND")
    database = commands.add_parser("db", help="database schema").add_subparsers(required=True, metavar="ACTION")
    database.add_parser("migrate", help="apply pending migrations").set_defaults(run=_migrate)
    database.add_parser("status", help="list applied and pending migrations").set_defaults(run=_status)
    return parser


def _migrate(settings: Settings) -> int:
    with psycopg.connect(settings.database_url) as connection:
        applied = migrations.migrate(connection)
    print(f"applied {len(applied)} migration(s)" + "".join(f"\n  {m.version:04d} {m.name}" for m in applied))
    return EXIT_OK


def _status(settings: Settings) -> int:
    with psycopg.connect(settings.database_url) as connection:
        done = {m.version for m in migrations.applied(connection)}
    for migration in migrations.available():
        print(f"{'applied' if migration.version in done else 'pending':8} {migration.version:04d} {migration.name}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
