"""The curation API as `metamorph api` wires it: real PostgreSQL, real S3, a curator's session over HTTP."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace

import httpx
import psycopg
import pytest
from contract_samples import PDF
from fastapi.testclient import TestClient
from metamorph_contract import Bundle, BundleWriter
from platform_samples import document

from metamorph_platform import wiring
from metamorph_platform.adapters.api.accounts import hash_password
from metamorph_platform.adapters.postgres.migrate import migrate
from metamorph_platform.config import Settings

pytestmark = [pytest.mark.database, pytest.mark.s3]
DOC = "ojk:pojk:2014:5"
GAPPY = "PERATURAN OTORITAS JASA KEUANGAN\nMEMUTUSKAN:\nPasal 1\nSatu.\nPasal 3\nTiga.\n"
FIXED = GAPPY.replace("Pasal 3", "Pasal 2\nDua.\nPasal 3")


@pytest.fixture
def settings(database_url):
    curators = [{"username": "ani", "name": "Ani Rahma", "password_hash": hash_password("rahasia", iterations=1_000)}]
    endpoint = os.environ.get("METAMORPH_TEST_S3_ENDPOINT_URL")
    settings = Settings(
        database_url=database_url,
        s3_bucket=f"metamorph-test-{uuid.uuid4().hex[:12]}",
        s3_endpoint_url=endpoint,
        curators=json.dumps(curators),
        web_secret="x" * 32,
    )
    blobs = wiring.blob_store(settings)
    blobs.ensure_bucket()
    yield settings
    for item in blobs.client.list_objects_v2(Bucket=blobs.bucket).get("Contents", []):
        blobs.client.delete_object(Bucket=blobs.bucket, Key=item["Key"])
    blobs.client.delete_bucket(Bucket=blobs.bucket)


def gappy_document(settings, tmp_path) -> str:
    """The sample document, its text missing Pasal 2: loaded, parsed, and published with the gap to review."""
    sample = document()
    text_ref = replace(sample.texts[0], sha256=hashlib.sha256(GAPPY.encode()).hexdigest(), paged=False)
    with BundleWriter(tmp_path / "b", connector="ojk", connector_version="0.1.0", run_id="run-1") as bundle:
        bundle.put_blob(PDF)
        bundle.put_text(GAPPY)
        bundle.add(replace(sample, texts=(text_ref,), provisions=()))
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        migrate(connection)
        wiring.load_bundle(connection, settings).run(Bundle(tmp_path / "b"), uri="x")
        wiring.parse_texts(connection, settings).run()
        assert wiring.publish(connection, settings).run().held == 0
    return text_ref.sha256


def session(settings) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(wiring.api_app(settings))
    token = client.post("/api/v1/auth/session", json={"username": "ani", "password": "rahasia"}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_a_curator_corrects_a_gap_and_the_text_leaves_the_gaps_list_within_the_request(settings, tmp_path) -> None:
    text_sha = gappy_document(settings, tmp_path)
    client, auth = session(settings)
    gaps = client.get("/api/v1/gaps", headers=auth).json()
    assert [(row["document_id"], row["notes"]) for row in gaps["rows"]] == [
        (DOC, [{"address": None, "note": "Pasal 2 missing"}])
    ]
    assert client.get("/api/v1/overview", headers=auth).json()["gaps"] == 1
    editable = client.get(f"/api/v1/documents/{DOC}/texts/{text_sha}/editable", headers=auth).json()

    response = client.post(
        f"/api/v1/documents/{DOC}/texts/{text_sha}/correction",
        headers=auth,
        json={"wording": editable["wording"].replace("Pasal 3", "Pasal 2\nDua.\nPasal 3"), "reason": "PDF hal. 2"},
    )

    assert response.status_code == 200
    assert response.json()["hold"] == [] and response.json()["published_at"] is not None
    assert client.get("/api/v1/gaps", headers=auth).json()["rows"] == []
    with psycopg.connect(settings.database_url) as connection:
        published = connection.execute("SELECT sha256 FROM published.text").fetchall()
        assert published == [(hashlib.sha256(FIXED.encode()).hexdigest(),)]
        assert connection.execute("SELECT author, action FROM curation.audit_log").fetchall() == [
            ("ani", "correct_text")
        ]


def test_a_curator_uploads_a_file_straight_to_the_store_and_adds_a_document(settings, tmp_path) -> None:
    gappy_document(settings, tmp_path)
    client, auth = session(settings)
    link = client.post("/api/v1/uploads", headers=auth, json={"file_name": "f.pdf", "media_type": "application/pdf"})

    httpx.put(link.json()["url"], content=b"%PDF-1.7 Fatwa 170", headers={"Content-Type": "application/pdf"})
    response = client.post(
        "/api/v1/documents",
        headers=auth,
        json={
            "document_id": "dsnmui:fatwa:170",
            "citation": "Fatwa DSN-MUI No. 170/DSN-MUI/X/2026",
            "title": "Pembiayaan Rumah Syariah",
            "kind": "fatwa",
            "status": "in_force",
            "source_url": "https://dsnmui.or.id/kategori/fatwa/",
            "reason": "Terbit setelah sync",
            "file_name": "f.pdf",
            "media_type": "application/pdf",
            "upload_key": link.json()["upload_key"],
        },
    )

    assert response.status_code == 200 and response.json()["summary"]["id"] == "dsnmui:fatwa:170"
    file_link = client.get(
        f"/api/v1/documents/dsnmui:fatwa:170/content/{hashlib.sha256(b'%PDF-1.7 Fatwa 170').hexdigest()}", headers=auth
    )
    assert httpx.get(file_link.json()["url"]).content == b"%PDF-1.7 Fatwa 170"
