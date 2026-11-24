"""Where a bundle lives between collection and processing: `<base>/<connector>/<run id>/`, in S3.

A bundle is complete only when its `_COMPLETE` marker exists, written after every other file, so a bundle
half-uploaded (the laptop slept) is never loaded.
"""

from __future__ import annotations

COMPLETE_MARKER = "_COMPLETE"


def run_location(connector_prefix: str, run_id: str) -> str:
    return f"{connector_prefix.rstrip('/')}/{run_id}"


def upload_location(base: str, connector: str, run_id: str) -> str:
    return run_location(run_location(base, connector), run_id)


def connector_of(connector_prefix: str) -> str:
    """The connector a prefix holds the bundles of: its last segment, `s3://ops/bundles/ojk` → `ojk`."""
    return connector_prefix.rstrip("/").rsplit("/", 1)[-1]
