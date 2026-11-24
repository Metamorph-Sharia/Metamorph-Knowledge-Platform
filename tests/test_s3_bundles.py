"""S3BundleStore against a stubbed S3 client: key layout, marker order, listing and download. No network."""

from __future__ import annotations

from pathlib import Path

import pytest
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError, NoCredentialsError, TokenRetrievalError, UnauthorizedSSOTokenError
from metamorph_contract import Bundle
from platform_samples import document, write_bundle

from metamorph_platform.adapters.blobs.bundles import S3BundleStore
from metamorph_platform.application.ports import BundleStoreAuthenticationError


def client_error(code: str, operation: str = "PutObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class StubS3:
    """The few calls the store makes, over a dict of (bucket, key) → bytes; `calls` records their order."""

    PAGE = 2  # a listing returns this many entries at a time, so pagination is exercised

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.failure: Exception | None = None

    def _fail(self) -> None:
        if self.failure:
            raise self.failure

    def upload_file(self, Filename: str, Bucket: str, Key: str, **_) -> None:
        self._fail()
        self.calls.append(("upload", Key))
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_) -> None:
        self._fail()
        self.calls.append(("put", Key))
        self.objects[(Bucket, Key)] = Body

    def delete_object(self, Bucket: str, Key: str) -> None:
        self._fail()
        self.calls.append(("delete", Key))
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket: str, Key: str) -> dict:
        self._fail()
        if (Bucket, Key) not in self.objects:
            raise client_error("404", "HeadObject")
        return {}

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
        self._fail()
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def get_paginator(self, operation: str) -> StubS3:
        assert operation == "list_objects_v2"
        return self

    def paginate(self, Bucket: str, Prefix: str, Delimiter: str | None = None):
        self._fail()
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        entries = (
            sorted(
                {
                    Prefix + key[len(Prefix) :].split(Delimiter)[0] + Delimiter
                    for key in keys
                    if Delimiter and Delimiter in key[len(Prefix) :]
                }
            )
            if Delimiter
            else keys
        )
        for start in range(0, max(len(entries), 1), self.PAGE):
            page = entries[start : start + self.PAGE]
            if Delimiter:
                yield {"CommonPrefixes": [{"Prefix": prefix} for prefix in page]}
            else:
                yield {"Contents": [{"Key": key} for key in page]}


@pytest.fixture
def s3() -> StubS3:
    return StubS3()


@pytest.fixture
def store(s3) -> S3BundleStore:
    return S3BundleStore(client=s3)


@pytest.fixture
def bundle_directory(tmp_path) -> Path:
    return write_bundle(tmp_path / "out", [document()], run_id="20261124T020000")


LOCATION = "s3://ops/bundles/ojk/20261124T020000"


def keys(s3: StubS3) -> set[str]:
    return {key for _, key in s3.objects}


def test_an_upload_copies_every_file_under_the_location_and_writes_the_marker_last(store, s3, bundle_directory) -> None:
    store.upload(bundle_directory, LOCATION)

    files = {path.relative_to(bundle_directory).as_posix() for path in bundle_directory.rglob("*") if path.is_file()}
    assert keys(s3) == {f"bundles/ojk/20261124T020000/{name}" for name in files} | {
        "bundles/ojk/20261124T020000/_COMPLETE"
    }
    assert any(name.startswith("blobs/") for name in files)  # nested files travel too
    assert s3.calls[-1] == ("put", "bundles/ojk/20261124T020000/_COMPLETE")
    assert store.is_complete(LOCATION)


def test_a_retried_upload_withdraws_the_old_marker_first_and_writes_it_again_last(store, s3, bundle_directory) -> None:
    store.upload(bundle_directory, LOCATION)
    s3.calls.clear()

    store.upload(bundle_directory, LOCATION)

    assert s3.calls[0] == ("delete", "bundles/ojk/20261124T020000/_COMPLETE")
    assert s3.calls[-1] == ("put", "bundles/ojk/20261124T020000/_COMPLETE")
    assert store.is_complete(LOCATION)


def test_a_bundle_is_not_complete_until_the_marker_is_written(store, s3, bundle_directory) -> None:
    s3.put_object("ops", "bundles/ojk/20261124T020000/manifest.json", b"{}")

    assert store.is_complete(LOCATION) is False


def test_the_runs_under_a_connectors_prefix_are_listed_across_pages(store, s3) -> None:
    for run_id in ["r1", "r2", "r3"]:
        s3.put_object("ops", f"bundles/ojk/{run_id}/manifest.json", b"{}")
    s3.put_object("ops", "bundles/ojk-other/r9/manifest.json", b"{}")  # another connector, a longer name

    assert sorted(store.runs("s3://ops/bundles/ojk")) == ["r1", "r2", "r3"]
    assert store.runs("s3://ops/bundles/ojk/") == store.runs("s3://ops/bundles/ojk")


def test_a_fetched_bundle_reads_back_and_its_scratch_directory_goes_away(store, bundle_directory) -> None:
    store.upload(bundle_directory, LOCATION)

    with store.fetch(LOCATION) as directory:
        bundle = Bundle(directory)
        assert bundle.manifest.run_id == "20261124T020000"
        assert [entry.is_valid for entry in bundle.entries()] == [True]
        assert not (directory / "_COMPLETE").exists()
    assert not directory.exists()


@pytest.mark.parametrize(
    "failure",
    [
        NoCredentialsError(),
        TokenRetrievalError(provider="sso", error_msg="expired"),
        UnauthorizedSSOTokenError(),
        client_error("ExpiredToken"),
        client_error("ExpiredTokenException"),
        client_error("InvalidClientTokenId"),
        S3UploadFailedError("Failed to upload a to ops/b: An error occurred (ExpiredToken) when calling PutObject"),
    ],
    ids=lambda failure: type(failure).__name__ + (getattr(failure, "response", {}).get("Error", {}).get("Code", "")),
)
def test_an_expired_or_missing_sign_in_is_reported_as_an_authentication_failure(
    store, s3, bundle_directory, failure
) -> None:
    s3.failure = failure

    with pytest.raises(BundleStoreAuthenticationError, match="aws sso login"):
        store.upload(bundle_directory, LOCATION)
    with pytest.raises(BundleStoreAuthenticationError):
        store.runs("s3://ops/bundles/ojk")
    with pytest.raises(BundleStoreAuthenticationError):
        store.is_complete(LOCATION)


def test_any_other_store_error_is_not_mistaken_for_a_sign_in_problem(store, s3, bundle_directory) -> None:
    s3.failure = client_error("AccessDenied")

    with pytest.raises(ClientError):
        store.upload(bundle_directory, LOCATION)


def test_a_location_must_be_an_s3_address(store, bundle_directory) -> None:
    with pytest.raises(ValueError, match="s3://"):
        store.upload(bundle_directory, "/tmp/somewhere")
