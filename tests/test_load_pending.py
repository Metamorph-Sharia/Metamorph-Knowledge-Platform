"""LoadPendingBundles against in-memory ports and a fake bundle store: which S3 bundles load, and in what order."""

from __future__ import annotations

import pytest
from fakes import (
    MemoryBlobStore,
    MemoryBundleStore,
    MemoryLedger,
    MemoryMarket,
    MemoryOverrides,
    MemoryRegistry,
    MemoryReviewQueue,
)
from market_platform_samples import licensed, write_market_bundle
from metamorph_contract import Bundle
from metamorph_market import Bundle as MarketBundle
from platform_samples import document, write_bundle

from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.load_pending import LoadPendingBundles

PREFIX = "s3://ops/bundles/ojk"


class World:
    """The regulation layer's ports and a bundle store, with a `bundle(run_id)` helper for the connector `ojk`."""

    def __init__(self, directory) -> None:
        self.directory = directory
        self.ledger, self.registry, self.store = MemoryLedger(), MemoryRegistry(), MemoryBundleStore()
        self.blobs, self.reviews, self.overrides = MemoryBlobStore(), MemoryReviewQueue(), MemoryOverrides()

    def bundle(self, run_id: str, *, complete: bool = True) -> None:
        directory = write_bundle(self.directory / run_id, [document(f"regalert:{run_id}")], run_id=run_id)
        self.store.add(PREFIX, run_id, directory, complete=complete)

    def a_pass(self):
        loader = LoadBundle(self.ledger, self.registry, self.blobs, self.reviews, self.overrides)
        return LoadPendingBundles(self.store, self.ledger, lambda d, uri: loader.run(Bundle(d), uri=uri)).run(PREFIX)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_a_complete_bundle_is_loaded(world) -> None:
    world.bundle("20261124T020000")

    report = world.a_pass()

    assert (report.loaded, report.skipped, report.held, report.incomplete) == (1, 0, 0, 0)
    assert world.ledger.bundles[1]["state"] == "loaded"
    assert world.store.fetched == [f"{PREFIX}/20261124T020000"]


def test_a_bundle_without_its_completion_marker_is_ignored(world) -> None:
    world.bundle("20261124T020000", complete=False)

    report = world.a_pass()

    assert (report.loaded, report.incomplete) == (0, 1)
    assert world.ledger.bundles == {} and world.store.fetched == []


def test_an_incomplete_bundle_stops_the_pass_so_nothing_lands_out_of_order(world) -> None:
    world.bundle("20261124T020000")
    world.bundle("20261125T020000", complete=False)  # an upload in progress
    world.bundle("20261126T020000")

    report = world.a_pass()

    assert (report.loaded, report.incomplete, report.waiting, report.held) == (1, 1, 1, 0)
    assert report.failed_run is None  # an upload in progress is not a failure
    assert world.store.fetched == [f"{PREFIX}/20261124T020000"]


def test_once_the_marker_is_there_the_waiting_bundles_load_in_order(world) -> None:
    world.bundle("20261125T020000", complete=False)
    world.bundle("20261126T020000")
    world.a_pass()

    world.store.add(PREFIX, "20261125T020000", world.directory / "20261125T020000")  # the upload finished

    report = world.a_pass()

    assert (report.loaded, report.incomplete, report.waiting) == (2, 0, 0)
    assert [location.rsplit("/", 1)[1] for location in world.store.fetched] == ["20261125T020000", "20261126T020000"]


def test_a_load_killed_part_way_is_retried_not_skipped(world) -> None:
    world.bundle("20261124T020000")
    killed = Bundle(world.directory / "20261124T020000")
    world.ledger.start_bundle(killed.manifest, "uri")  # received, and then the process died

    report = world.a_pass()

    assert (report.loaded, report.skipped) == (1, 0)
    assert world.ledger.bundles[1]["state"] == "loaded"


def test_a_bundle_already_loaded_is_skipped_without_downloading_it_again(world) -> None:
    world.bundle("20261124T020000")
    world.a_pass()
    world.store.fetched.clear()

    report = world.a_pass()

    assert (report.loaded, report.skipped) == (0, 1)
    assert world.store.fetched == []


def test_bundles_load_oldest_first_by_run_id(world) -> None:
    for run_id in ["20261126T020000", "20261124T020000", "20261125T020000"]:
        world.bundle(run_id)

    world.a_pass()

    assert [location.rsplit("/", 1)[1] for location in world.store.fetched] == [
        "20261124T020000",
        "20261125T020000",
        "20261126T020000",
    ]


def test_a_failure_holds_the_later_bundles_and_the_next_pass_resumes_from_it(world) -> None:
    for run_id in ["20261124T020000", "20261125T020000", "20261126T020000"]:
        world.bundle(run_id)
    save = world.registry.save
    saves = []

    def breaks_on_the_second(document, **kwargs):
        saves.append(document)
        if len(saves) == 2:
            raise RuntimeError("database went away")
        return save(document, **kwargs)

    world.registry.save = breaks_on_the_second

    first = world.a_pass()

    assert (first.loaded, first.held) == (1, 2)  # the failed bundle and the one behind it
    assert first.failed_run == "20261125T020000" and "database went away" in first.error
    assert [b["state"] for b in world.ledger.bundles.values()] == ["loaded", "failed"]

    second = world.a_pass()

    assert (second.loaded, second.skipped, second.held) == (2, 1, 0)
    assert second.failed_run is None
    assert {b["state"] for b in world.ledger.bundles.values()} == {"loaded"}


def test_a_bundle_that_cannot_be_read_is_held_like_any_other_failure(world, tmp_path) -> None:
    world.store.add(PREFIX, "20261124T020000", tmp_path / "no-such-bundle")  # a marker, but nothing inside

    report = world.a_pass()

    assert (report.loaded, report.held, report.failed_run) == (0, 1, "20261124T020000")


def test_market_bundles_go_to_the_market_layer(tmp_path) -> None:
    prefix = "s3://ops/bundles/ojk-register"
    ledger, market, store = MemoryLedger(), MemoryMarket(), MemoryBundleStore()
    store.add(prefix, "run-1", write_market_bundle(tmp_path / "b1", [licensed("KEP-1/D.05/2021", "2021-01-31")]))
    loader = LoadMarketBundle(ledger, market, MemoryBlobStore(), MemoryReviewQueue())

    report = LoadPendingBundles(store, ledger, lambda d, uri: loader.run(MarketBundle(d), uri=uri)).run(prefix)

    assert report.loaded == 1
    assert ("ojk-register", "KEP-1/D.05/2021") in market.records


def test_the_bundles_uri_is_its_s3_location(world) -> None:
    uris = []
    world.bundle("20261124T020000")

    LoadPendingBundles(world.store, world.ledger, lambda directory, uri: uris.append(uri)).run(PREFIX)

    assert uris == [f"{PREFIX}/20261124T020000"]
