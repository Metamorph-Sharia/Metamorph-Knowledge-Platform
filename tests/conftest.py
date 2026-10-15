"""Database tests run against a real PostgreSQL, each in a database of its own, created and dropped here.

Set METAMORPH_TEST_DATABASE_URL to a server you may create databases on, e.g. the compose stack:
    METAMORPH_TEST_DATABASE_URL=postgresql://metamorph:metamorph-dev@localhost:5433/postgres uv run pytest
Without it, tests marked `database` are skipped. Tests marked `s3` need METAMORPH_TEST_S3_ENDPOINT_URL
(e.g. http://localhost:8333) and the AWS_* credentials from .env.example.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SERVER_URL = os.environ.get("METAMORPH_TEST_DATABASE_URL")
S3_ENDPOINT_URL = os.environ.get("METAMORPH_TEST_S3_ENDPOINT_URL")  # plus the AWS_* credentials (see .env.example)
NEEDS = {  # marker: (the variable that enables it, its value)
    "database": ("METAMORPH_TEST_DATABASE_URL", SERVER_URL),
    "s3": ("METAMORPH_TEST_S3_ENDPOINT_URL", S3_ENDPOINT_URL),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for marker, (variable, value) in NEEDS.items():
        if value:
            continue
        skip = pytest.mark.skip(reason=f"{variable} is not set")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def database_url() -> Iterator[str]:
    name = f"metamorph_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(SERVER_URL, autocommit=True) as server:
        server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(**{**conninfo_to_dict(SERVER_URL), "dbname": name})
    finally:
        with psycopg.connect(SERVER_URL, autocommit=True) as server:
            server.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url) as connection:
        yield connection
