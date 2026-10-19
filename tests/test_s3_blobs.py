"""S3BlobStore against a real S3-compatible store (SeaweedFS in the compose stack)."""

from __future__ import annotations

import hashlib
import os
import uuid

import httpx
import pytest

from metamorph_platform.adapters.blobs.s3 import S3BlobStore, S3FileLinks, storage_key

pytestmark = pytest.mark.s3


@pytest.fixture
def store():
    blobs = S3BlobStore(f"metamorph-test-{uuid.uuid4().hex[:12]}", os.environ.get("METAMORPH_TEST_S3_ENDPOINT_URL"))
    assert blobs.ensure_bucket() is True
    yield blobs
    for item in blobs.client.list_objects_v2(Bucket=blobs.bucket).get("Contents", []):
        blobs.client.delete_object(Bucket=blobs.bucket, Key=item["Key"])
    blobs.client.delete_bucket(Bucket=blobs.bucket)


def test_a_blob_is_stored_once_under_its_content_address(store, tmp_path) -> None:
    data = b"%PDF-1.7 POJK 5/POJK.05/2014"
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / "blob").write_bytes(data)

    first = store.store(sha, tmp_path / "blob", "application/pdf")
    second = store.store(sha, tmp_path / "blob", "application/pdf")

    assert first == second
    assert first.storage_key == storage_key(sha) == f"blobs/{sha[:2]}/{sha}"
    assert store.read(first.storage_key) == data
    assert store.client.head_object(Bucket=store.bucket, Key=first.storage_key)["ContentType"] == "application/pdf"


def test_ensuring_an_existing_bucket_changes_nothing(store) -> None:
    assert store.ensure_bucket() is False


def test_bytes_in_hand_are_stored_once_under_their_content_address(store) -> None:
    """A curator's corrected text comes from a form, not a file."""
    data = b"Pasal 1\nSatu.\n"
    sha = hashlib.sha256(data).hexdigest()

    first = store.put(sha, data, "text/markdown; charset=utf-8")

    assert first == store.put(sha, data, "text/markdown; charset=utf-8")
    assert (first.storage_key, first.size_bytes) == (storage_key(sha), len(data))
    assert store.read(first.storage_key) == data


@pytest.fixture
def links(store):
    return S3FileLinks(store.bucket, os.environ.get("METAMORPH_TEST_S3_ENDPOINT_URL"))


def test_a_browser_uploads_through_a_short_lived_link_and_the_api_reads_it_back(links) -> None:
    url = links.upload_url("uploads/abc", media_type="application/pdf")

    assert httpx.put(url, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"}).status_code == 200
    assert links.uploaded("uploads/abc") == b"%PDF-1.7"
    assert links.uploaded("uploads/never") is None


def test_a_file_opens_through_a_short_lived_link_named_and_typed(store, links, tmp_path) -> None:
    (tmp_path / "blob").write_bytes(b"Pasal 1")
    stored = store.store(hashlib.sha256(b"Pasal 1").hexdigest(), tmp_path / "blob", "text/markdown")

    url = links.download_url(stored.storage_key, name="id-aaaa.md", media_type="text/markdown")
    response = httpx.get(url)

    assert response.content == b"Pasal 1"
    assert response.headers["content-type"].startswith("text/markdown")
    assert "id-aaaa.md" in url  # S3 names the file so; SeaweedFS, here, ignores the name it is asked for


def test_links_are_signed_for_the_address_browsers_use(store) -> None:
    """Inside Docker the API reaches the store as objectstore:8333; a browser only as localhost:8333."""
    links = S3FileLinks(store.bucket, "http://objectstore:8333", public_endpoint_url="http://localhost:8333")

    assert links.upload_url("uploads/abc", media_type="application/pdf").startswith("http://localhost:8333/")


def test_browsers_on_the_curation_web_app_may_upload_and_no_one_else(store) -> None:
    """The web app's add-document form puts the file straight into the bucket (ADR-5)."""
    store.allow_uploads_from(["https://curation.example"])

    def preflight(origin: str) -> httpx.Response:
        return httpx.options(
            f"{os.environ['METAMORPH_TEST_S3_ENDPOINT_URL']}/{store.bucket}/uploads/x",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert (
        preflight("https://curation.example").headers.get("access-control-allow-origin") == "https://curation.example"
    )
    assert preflight("https://elsewhere.example").headers.get("access-control-allow-origin") is None
