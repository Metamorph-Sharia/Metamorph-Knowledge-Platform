"""Send a collected bundle (either layer's contract) to the store where processing looks for it.

The destination comes from the bundle's own manifest, so a bundle can't be filed under another connector's prefix.
"""

from __future__ import annotations

import json
from pathlib import Path

from metamorph_contract import UnloadableBundle

from metamorph_platform.application.ports import BundleSink
from metamorph_platform.domain.bundle_locations import upload_location

MANIFEST = "manifest.json"


class UploadBundle:
    def __init__(self, sink: BundleSink) -> None:
        self.sink = sink

    def run(self, directory: Path, base: str) -> str:
        """The location the bundle was uploaded to. Refuses a bundle whose export did not finish."""
        manifest = _manifest(directory)
        location = upload_location(base, manifest["connector"], manifest["run_id"])
        self.sink.upload(directory, location)
        return location


def _manifest(directory: Path) -> dict:
    path = directory / MANIFEST
    if not path.is_file():
        raise UnloadableBundle(f"{directory}: no manifest, the export did not finish")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("complete") is not True:
        raise UnloadableBundle(f"{directory}: the manifest says the export is not complete")
    return manifest
