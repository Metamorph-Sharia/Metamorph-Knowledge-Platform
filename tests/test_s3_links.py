"""Short-lived file links, as signed without a store: signing needs credentials and a region, not a network."""

from __future__ import annotations

import pytest

from metamorph_platform.adapters.blobs.s3 import S3FileLinks


@pytest.fixture(autouse=True)
def aws(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-3")


def test_on_aws_links_go_to_the_buckets_own_region() -> None:
    """S3's global address can't send a request on to an opt-in region such as Jakarta's: the browser would get
    IllegalLocationConstraintException instead of the file."""
    links = S3FileLinks("metamorph-blobs")

    for url in (
        links.download_url("blobs/ab/abc", name="a.pdf", media_type="application/pdf"),
        links.upload_url("uploads/abc", media_type="application/pdf"),
    ):
        assert url.startswith("https://metamorph-blobs.s3.ap-southeast-3.amazonaws.com/")


def test_an_s3_compatible_store_keeps_its_own_address() -> None:
    links = S3FileLinks("metamorph-blobs", "http://objectstore:8333", public_endpoint_url="http://localhost:8333")

    assert links.upload_url("uploads/abc", media_type="application/pdf").startswith(
        "http://localhost:8333/metamorph-blobs/uploads/abc?"
    )
