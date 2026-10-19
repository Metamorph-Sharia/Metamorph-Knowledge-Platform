"""The curation app as `metamorph web` wires it: real PostgreSQL, real S3, a correction over HTTP."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace

import psycopg
import pytest
from contract_samples import PDF
from fastapi.testclient import TestClient
from metamorph_contract import Bundle, BundleWriter
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
        wiring.parse_texts(connection, settings).run()
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


GAPPY = "PERATURAN OTORITAS JASA KEUANGAN\nMEMUTUSKAN:\nPasal 1\nSatu.\nPasal 3\nTiga.\n"


def gappy_bundle(directory):
    """The sample document, with a text whose Pasal 2 is missing: the publish gate holds it."""
    sample = document()
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(GAPPY.encode()).hexdigest(), paged=False)
    with BundleWriter(directory, connector="ojk", connector_version="0.1.0", run_id="run-1") as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(GAPPY)
        bundle.add(replace(sample, texts=(text_ref,), provisions=()))
    return directory, text_ref.sha256


def test_a_held_document_approved_in_the_app_is_published(settings, tmp_path) -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        migrate(connection)
        directory, text_sha = gappy_bundle(tmp_path / "b")
        wiring.load_bundle(connection, settings).run(Bundle(directory), uri="x")
        wiring.parse_texts(connection, settings).run()
        assert wiring.publish(connection, settings).run().held == 1
    client = TestClient(wiring.web_app(settings))
    client.auth = ("ani", "rahasia")
    assert DOC in client.get("/held").text
    token = client.get(f"/documents/{DOC}").text.split('name="csrf" value="')[1].split('"')[0]

    response = client.post(
        f"/documents/{DOC}/texts/{text_sha}/approve", data={"csrf": token, "reason": "Pasal 2 dicabut"}
    )

    assert response.status_code == 200 and "Approved." in response.text and "Held back" not in response.text
    with psycopg.connect(settings.database_url) as connection:
        assert connection.execute("SELECT count(*) FROM published.document").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM registry.hold").fetchone() == (0,)


def test_a_text_corrected_in_the_app_is_parsed_and_published_within_the_request(settings, tmp_path) -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        migrate(connection)
        directory, text_sha = gappy_bundle(tmp_path / "b")
        wiring.load_bundle(connection, settings).run(Bundle(directory), uri="x")
        wiring.parse_texts(connection, settings).run()
        wiring.publish(connection, settings).run()
    client = TestClient(wiring.web_app(settings))
    client.auth = ("ani", "rahasia")
    edit = client.get(f"/documents/{DOC}/texts/{text_sha}/edit").text
    token = edit.split('name="csrf" value="')[1].split('"')[0]
    fixed = GAPPY.replace("Pasal 3", "Pasal 2\nDua.\nPasal 3")

    response = client.post(
        f"/documents/{DOC}/texts/{text_sha}/correction",
        data={"csrf": token, "wording": fixed, "reason": "PDF halaman 2"},
    )

    assert response.status_code == 200 and "Text corrected" in response.text and "Held back" not in response.text
    fixed_sha = hashlib.sha256(fixed.encode()).hexdigest()
    with psycopg.connect(settings.database_url) as connection:
        assert connection.execute("SELECT sha256 FROM published.text").fetchall() == [(fixed_sha,)]
        bodies = dict(connection.execute("SELECT address, body FROM published.provision").fetchall())
        assert bodies["pasal-2"] == "Pasal 2\nDua.\n"
    assert "+Pasal 2" in client.get(f"/documents/{DOC}/texts/{text_sha}/correction").text
