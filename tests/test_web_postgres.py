"""The curation app as `metamorph web` wires it: real PostgreSQL, real S3, a correction over HTTP."""

from __future__ import annotations

import json
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from metamorph_contract import Bundle
from platform_samples import document, write_bundle

from metamorph_platform import wiring
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.adapters.web.accounts import hash_password
from metamorph_platform.config import Settings

pytestmark = [pytest.mark.database, pytest.mark.s3]
DOC = "ojk:pojk:2014:5"


@pytest.fixture
def settings(database_url):
    curators = [{"username": "ani", "name": "Ani Rahma", "password_hash": hash_password("rahasia", iterations=1_000)}]
    settings = Settings(
        database_url=database_url,
        s3_bucket=f"metamorph-test-{uuid.uuid4().hex[:12]}",
        s3_endpoint_url=os.environ.get("METAMORPH_TEST_S3_ENDPOINT_URL"),
        curators=json.dumps(curators),
        web_secret="x" * 32,
    )
    blobs = wiring.blob_store(settings)
    blobs.ensure_bucket()
    yield settings
    for item in blobs.client.list_objects_v2(Bucket=blobs.bucket).get("Contents", []):
        blobs.client.delete_object(Bucket=blobs.bucket, Key=item["Key"])
    blobs.client.delete_bucket(Bucket=blobs.bucket)


def test_a_correction_made_in_the_app_reaches_published_and_the_audit_log(settings, tmp_path) -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        migrate(connection)
        wiring.load_bundle(connection, settings).run(Bundle(write_bundle(tmp_path / "b", [document()])), uri="x")
        wiring.publish(connection, settings).run()
    client = TestClient(wiring.web_app(settings))
    client.auth = ("ani", "rahasia")
    token = client.get(f"/documents/{DOC}").text.split('name="csrf" value="')[1].split('"')[0]

    response = client.post(
        f"/documents/{DOC}/corrections",
        data={"csrf": token, "field": "title", "value": "Perizinan Usaha", "reason": "Judul resmi"},
    )

    assert response.status_code == 200 and "Correction saved and published." in response.text
    with psycopg.connect(settings.database_url) as connection:
        published = connection.execute("SELECT title, curated FROM published.document WHERE id = %s", (DOC,))
        assert published.fetchone() == ("Perizinan Usaha", True)
        audit = connection.execute("SELECT author, action, reason FROM curation.audit_log").fetchall()
        assert audit == [("ani", "correct", "Judul resmi")]
    assert client.get(f"/documents/{DOC}/content/{document().texts[0].sha256}").text.startswith("<!-- page 1 -->")
