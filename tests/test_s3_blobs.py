"""S3BlobStore against a real S3-compatible store (SeaweedFS in the compose stack)."""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest

from metamorph_platform.adapters.blobs.s3 import S3BlobStore, storage_key

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
