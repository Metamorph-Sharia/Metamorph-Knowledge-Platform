from pathlib import Path

import pytest

from metamorph_platform.adapters.postgres.migrate import Migration, MigrationError, applied, available, migrate

SCHEMAS = {"ingest", "registry", "curation", "published"}


def write(directory: Path, name: str, sql: str = "SELECT 1;") -> None:
    (directory / name).write_text(sql)


# --- files (no database) ----------------------------------------------------------


def test_the_shipped_migrations_are_numbered_without_gaps() -> None:
    assert [m.version for m in available()] == list(range(1, len(available()) + 1))


def test_a_gap_in_the_numbering_is_refused(tmp_path) -> None:
    write(tmp_path, "0001_first.sql")
    write(tmp_path, "0003_third.sql")

    with pytest.raises(MigrationError, match="without gaps"):
        available(tmp_path)


def test_a_badly_named_file_is_refused(tmp_path) -> None:
    write(tmp_path, "1_first.sql")

    with pytest.raises(MigrationError, match="NNNN_name.sql"):
        available(tmp_path)


# --- against PostgreSQL ---------------------------------------------------------------


def schemas_in(connection) -> set[str]:
    rows = connection.execute("SELECT nspname FROM pg_namespace")
    return {name for (name,) in rows} & SCHEMAS


@pytest.mark.database
def test_migrations_build_every_schema_from_an_empty_database(connection) -> None:
    done = migrate(connection)

    assert [m.version for m in done] == [m.version for m in available()]
    assert schemas_in(connection) == SCHEMAS
    assert [m.name for m in applied(connection)] == [m.name for m in available()]


@pytest.mark.database
def test_migrating_twice_changes_nothing(connection) -> None:
    migrate(connection)

    assert migrate(connection) == []


@pytest.mark.database
def test_status_on_an_empty_database_writes_nothing(connection) -> None:
    assert applied(connection) == []
    (bookkeeping,) = connection.execute("SELECT to_regnamespace('platform_meta')").fetchone()
    assert bookkeeping is None


@pytest.mark.database
def test_an_edited_migration_is_refused(connection) -> None:
    migrate(connection)
    edited = [Migration(m.version, m.name, m.sql + "\n-- edited") for m in available()]

    with pytest.raises(MigrationError, match="were edited"):
        migrate(connection, edited)


@pytest.mark.database
def test_a_failing_migration_leaves_the_database_as_it_was(connection) -> None:
    broken = [*available(), Migration(len(available()) + 1, "broken", "CREATE TABLE ingest.x (;")]

    with pytest.raises(Exception, match="syntax error"):
        migrate(connection, broken)

    assert schemas_in(connection) == set()
    assert applied(connection) == []
