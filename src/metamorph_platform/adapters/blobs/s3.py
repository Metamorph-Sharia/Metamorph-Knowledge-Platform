"""Blobs in any S3-compatible object store (SeaweedFS locally; AWS S3 or GCS's S3 API in the cloud).

Credentials come from boto3's standard sources (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, …), never from config.
"""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from metamorph_platform.application.ports import StoredBlob

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}
LINK_LIFETIME_SECONDS = 15 * 60  # long enough to open a file or upload 100 MB


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

    def allow_uploads_from(self, origins: list[str]) -> None:
        """Browsers on these origins (the curation web app) may PUT files into the bucket through presigned links."""
        rule = {
            "AllowedOrigins": origins,
            "AllowedMethods": ["PUT"],
            "AllowedHeaders": ["content-type"],
            "MaxAgeSeconds": 3600,
        }
        self.client.put_bucket_cors(Bucket=self.bucket, CORSConfiguration={"CORSRules": [rule]})

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


class S3FileLinks:
    """Short-lived links straight to the bucket, so files never pass through the API or the web app.

    `public_endpoint_url`: the address browsers reach the store at, when it isn't the one this process uses
    (locally the API reaches SeaweedFS as objectstore:8333, a browser as localhost:8333). Unset on AWS S3.
    """

    def __init__(self, bucket: str, endpoint_url: str | None = None, *, public_endpoint_url: str | None = None) -> None:
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url)
        # SigV4 explicitly: S3-compatible stores (SeaweedFS) refuse other presigned signatures. On AWS itself, virtual
        # addressing explicitly, or botocore signs for S3's global address, which can't reach an opt-in region's bucket.
        signer_endpoint = public_endpoint_url or endpoint_url
        addressing = {} if signer_endpoint else {"s3": {"addressing_style": "virtual"}}
        self.signer = boto3.client(
            "s3", endpoint_url=signer_endpoint, config=Config(signature_version="s3v4", **addressing)
        )

    def download_url(self, storage_key: str, *, name: str, media_type: str) -> str:
        parameters = {
            "Bucket": self.bucket,
            "Key": storage_key,
            "ResponseContentType": media_type,
            "ResponseContentDisposition": f'inline; filename="{name}"',
        }
        return self.signer.generate_presigned_url("get_object", Params=parameters, ExpiresIn=LINK_LIFETIME_SECONDS)

    def upload_url(self, key: str, *, media_type: str) -> str:
        parameters = {"Bucket": self.bucket, "Key": key, "ContentType": media_type}
        return self.signer.generate_presigned_url("put_object", Params=parameters, ExpiresIn=LINK_LIFETIME_SECONDS)

    def uploaded(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as error:
            if error.response["Error"]["Code"] in _NOT_FOUND:
                return None
            raise
