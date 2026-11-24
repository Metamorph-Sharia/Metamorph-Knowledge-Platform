"""Bundles in S3, between collection and processing: `s3://<bucket>/bundles/<connector>/<run id>/…`.

Credentials come from boto3's standard sources: the collection host's SSO session, a task role on AWS. When they
are missing or expired, every call raises BundleStoreAuthenticationError so the CLI can say what to do.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    NoCredentialsError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

from metamorph_platform.application.ports import BundleStoreAuthenticationError
from metamorph_platform.domain.bundle_locations import COMPLETE_MARKER

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}
_SIGN_IN_PROBLEMS = (
    NoCredentialsError,
    CredentialRetrievalError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
    SSOTokenLoadError,
)
_EXPIRED_CODES = ("ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "UnrecognizedClientException")
SIGN_IN_ADVICE = "AWS refused the credentials: sign in again with `aws sso login`, then retry"


class S3BundleStore:
    def __init__(self, endpoint_url: str | None = None, *, client: Any = None) -> None:
        self.client = client or boto3.client("s3", endpoint_url=endpoint_url)

    def upload(self, directory: Path, location: str) -> None:
        bucket, prefix = _split(location)
        with _signed_in():
            marker = f"{prefix}/{COMPLETE_MARKER}"
            self.client.delete_object(Bucket=bucket, Key=marker)  # a retry is incomplete until it is whole again
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    key = f"{prefix}/{path.relative_to(directory).as_posix()}"
                    self.client.upload_file(str(path), bucket, key)
            self.client.put_object(Bucket=bucket, Key=marker, Body=b"")

    def runs(self, connector_prefix: str) -> list[str]:
        bucket, prefix = _split(connector_prefix)
        with _signed_in():
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=f"{prefix}/", Delimiter="/"
            )
            return [
                entry["Prefix"].removeprefix(f"{prefix}/").rstrip("/")
                for page in pages
                for entry in page.get("CommonPrefixes", [])
            ]

    def is_complete(self, location: str) -> bool:
        bucket, prefix = _split(location)
        with _signed_in():
            try:
                self.client.head_object(Bucket=bucket, Key=f"{prefix}/{COMPLETE_MARKER}")
            except ClientError as error:
                if error.response["Error"]["Code"] in _NOT_FOUND:
                    return False
                raise
            return True

    @contextmanager
    def fetch(self, location: str) -> Iterator[Path]:
        bucket, prefix = _split(location)
        with tempfile.TemporaryDirectory(prefix="metamorph-bundle-") as scratch, _signed_in():
            directory = Path(scratch)
            pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/")
            for page in pages:
                for item in page.get("Contents", []):
                    name = item["Key"].removeprefix(f"{prefix}/")
                    if name != COMPLETE_MARKER:
                        target = directory / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        self.client.download_file(bucket, item["Key"], str(target))
            yield directory


def _split(location: str) -> tuple[str, str]:
    """`s3://bucket/some/prefix/` → ("bucket", "some/prefix")."""
    if not location.startswith("s3://"):
        raise ValueError(f"not an S3 address (s3://bucket/prefix): {location}")
    bucket, _, key = location.removeprefix("s3://").partition("/")
    return bucket, key.rstrip("/")


@contextmanager
def _signed_in() -> Iterator[None]:
    """Re-raise what an expired or missing sign-in looks like, in boto3's several shapes, as one error."""
    try:
        yield
    except _SIGN_IN_PROBLEMS as error:
        raise BundleStoreAuthenticationError(SIGN_IN_ADVICE) from error
    except ClientError as error:
        if error.response["Error"]["Code"] not in _EXPIRED_CODES:
            raise
        raise BundleStoreAuthenticationError(SIGN_IN_ADVICE) from error
    except S3UploadFailedError as error:  # boto3 wraps an upload's ClientError into a message
        if not any(code in str(error) for code in _EXPIRED_CODES):
            raise
        raise BundleStoreAuthenticationError(SIGN_IN_ADVICE) from error
