"""UploadBundle against a fake bundle store: where a collected bundle goes, and which bundles never leave the host."""

from __future__ import annotations

import json

import pytest
from fakes import MemoryBundleStore
from market_platform_samples import licensed, write_market_bundle
from metamorph_contract import UnloadableBundle
from platform_samples import document, write_bundle

from metamorph_platform.application.upload_bundle import UploadBundle


def test_a_bundle_goes_under_its_connector_and_run(tmp_path) -> None:
    store = MemoryBundleStore()
    directory = write_bundle(tmp_path / "out", [document()], run_id="20261124T020000")

    location = UploadBundle(store).run(directory, "s3://ops/bundles")

    assert location == "s3://ops/bundles/ojk/20261124T020000"
    assert store.uploaded == {location: directory}


def test_a_market_bundle_is_placed_the_same_way(tmp_path) -> None:
    store = MemoryBundleStore()
    directory = write_market_bundle(tmp_path / "out", [licensed("KEP-1/D.05/2021", "2021-01-31")], run_id="r7")

    assert UploadBundle(store).run(directory, "s3://ops/bundles/") == "s3://ops/bundles/ojk-register/r7"


def test_a_directory_without_a_manifest_is_refused(tmp_path) -> None:
    store = MemoryBundleStore()
    (tmp_path / "half").mkdir()

    with pytest.raises(UnloadableBundle):
        UploadBundle(store).run(tmp_path / "half", "s3://ops/bundles")

    assert store.uploaded == {}


def test_a_bundle_whose_export_did_not_finish_is_refused(tmp_path) -> None:
    store = MemoryBundleStore()
    directory = write_bundle(tmp_path / "out", [document()])
    manifest = json.loads((directory / "manifest.json").read_text())
    (directory / "manifest.json").write_text(json.dumps({**manifest, "complete": False}))

    with pytest.raises(UnloadableBundle):
        UploadBundle(store).run(directory, "s3://ops/bundles")

    assert store.uploaded == {}
