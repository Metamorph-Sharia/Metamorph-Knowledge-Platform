"""Blobs in any S3-compatible object store (SeaweedFS locally; AWS S3 or GCS's S3 API in the cloud).

Credentials come from boto3's standard sources (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, …), never from config.
"""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from metamorph_platform.application.ports import StoredBlob

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


def storage_key(sha256: str) -> str:
    return f"blobs/{sha256[:2]}/{sha256}"


class S3BlobStore:
    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def store(self, sha256: str, source: Path, media_type: str) -> StoredBlob:
        key = storage_key(sha256)
        if not self._exists(key):
            self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": media_type})
        return StoredBlob(sha256=sha256, storage_key=key, media_type=media_type, size_bytes=source.stat().st_size)

    def put(self, sha256: str, data: bytes, media_type: str) -> StoredBlob:
        key = storage_key(sha256)
        if not self._exists(key):
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=media_type)
        return StoredBlob(sha256=sha256, storage_key=key, media_type=media_type, size_bytes=len(data))

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def ensure_bucket(self) -> bool:
        """Create the bucket if it doesn't exist; True when it was created."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return False
        except ClientError as error:
            if error.response["Error"]["Code"] not in _NOT_FOUND:
                raise
        self.client.create_bucket(Bucket=self.bucket)
        return True

    def _exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as error:
            if error.response["Error"]["Code"] in _NOT_FOUND:
                return False
            raise
