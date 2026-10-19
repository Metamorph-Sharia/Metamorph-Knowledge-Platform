"""Settings come from the environment, so secrets never live in files or the repository."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_BUCKET = "metamorph-blobs"
MIN_SECRET_LENGTH = 32


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str  # METAMORPH_DATABASE_URL, e.g. postgresql://metamorph:…@localhost:5433/metamorph
    s3_bucket: str = DEFAULT_BUCKET  # METAMORPH_S3_BUCKET
    s3_endpoint_url: str | None = None  # METAMORPH_S3_ENDPOINT_URL; unset means AWS S3 itself
    # METAMORPH_S3_PUBLIC_ENDPOINT_URL: where browsers reach the store, if not there (the API's file links)
    s3_public_endpoint_url: str | None = None
    curators: str | None = None  # METAMORPH_CURATORS: the curation team's accounts (JSON)
    web_secret: str | None = None  # METAMORPH_WEB_SECRET: signs the curation API's session tokens

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] = os.environ) -> Settings:
        if not environment.get("METAMORPH_DATABASE_URL"):
            raise ConfigurationError("set METAMORPH_DATABASE_URL (see .env.example)")
        return cls(
            database_url=environment["METAMORPH_DATABASE_URL"],
            s3_bucket=environment.get("METAMORPH_S3_BUCKET") or DEFAULT_BUCKET,
            s3_endpoint_url=environment.get("METAMORPH_S3_ENDPOINT_URL") or None,
            s3_public_endpoint_url=environment.get("METAMORPH_S3_PUBLIC_ENDPOINT_URL") or None,
            curators=environment.get("METAMORPH_CURATORS") or None,
            web_secret=environment.get("METAMORPH_WEB_SECRET") or None,
        )

    def require_curation(self) -> tuple[str, str]:
        """The curation team's accounts and the session tokens' secret; only `metamorph api` needs them."""
        if not self.curators:
            raise ConfigurationError("set METAMORPH_CURATORS: the team's accounts (see .env.example)")
        if not self.web_secret or len(self.web_secret) < MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"set METAMORPH_WEB_SECRET to {MIN_SECRET_LENGTH}+ random characters, e.g. `openssl rand -hex 32`"
            )
        return self.curators, self.web_secret
