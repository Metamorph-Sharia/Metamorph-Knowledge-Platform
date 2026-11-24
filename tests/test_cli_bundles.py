"""The bundle commands through `main`: upload-bundle, load from an S3 location, load-pending. Ports are in memory."""

from __future__ import annotations

import json
from contextlib import nullcontext

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

from metamorph_platform import cli, wiring
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.load_pending import LoadPendingBundles
from metamorph_platform.application.ports import BundleStoreAuthenticationError
from metamorph_platform.application.upload_bundle import UploadBundle

OJK = "s3://ops/bundles/ojk"
REGISTER = "s3://ops/bundles/ojk-register"


@pytest.fixture
def world(monkeypatch):
    """The CLI wired to in-memory ports, as `wiring` would wire it to PostgreSQL and S3."""

    class World:
        ledger, registry, market, store = MemoryLedger(), MemoryRegistry(), MemoryMarket(), MemoryBundleStore()

    w = World()
    loader = LoadBundle(w.ledger, w.registry, MemoryBlobStore(), MemoryReviewQueue(), MemoryOverrides())
    market_loader = LoadMarketBundle(w.ledger, w.market, MemoryBlobStore(), MemoryReviewQueue())
    monkeypatch.setenv("METAMORPH_DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(wiring, "connect", lambda settings: nullcontext())
    monkeypatch.setattr(wiring, "bundle_store", lambda settings=None: w.store)
    monkeypatch.setattr(wiring, "load_bundle", lambda connection, settings: loader)
    monkeypatch.setattr(wiring, "load_market_bundle", lambda connection, settings: market_loader)
    monkeypatch.setattr(
        wiring,
        "load_pending_bundles",
        lambda connection, settings: LoadPendingBundles(
            w.store, w.ledger, lambda d, uri: loader.run(Bundle(d), uri=uri)
        ),
    )
    monkeypatch.setattr(
        wiring,
        "load_pending_market_bundles",
        lambda connection, settings: LoadPendingBundles(
            w.store, w.ledger, lambda d, uri: market_loader.run(MarketBundle(d), uri=uri)
        ),
    )
    monkeypatch.setattr(wiring, "upload_bundle", lambda: UploadBundle(w.store))
    return w


def test_load_reads_a_bundle_from_s3_and_records_the_location_as_its_uri(world, tmp_path, capsys) -> None:
    world.store.add(OJK, "run-1", write_bundle(tmp_path / "b1", [document()]))

    assert cli.main(["load", f"{OJK}/run-1"]) == 0

    assert json.loads(capsys.readouterr().out)["new"] == 1
    assert world.ledger.bundles[1]["uri"] == f"{OJK}/run-1"


def test_market_load_reads_a_bundle_from_s3_too(world, tmp_path) -> None:
    world.store.add(
        REGISTER, "run-1", write_market_bundle(tmp_path / "b1", [licensed("KEP-1/D.05/2021", "2021-01-31")])
    )

    assert cli.main(["market", "load", f"{REGISTER}/run-1"]) == 0

    assert ("ojk-register", "KEP-1/D.05/2021") in world.market.records


def test_load_still_reads_a_directory(world, tmp_path) -> None:
    directory = write_bundle(tmp_path / "b1", [document()])

    assert cli.main(["load", str(directory)]) == 0

    assert world.ledger.bundles[1]["uri"] == str(directory.resolve())


def test_load_pending_reports_counts_and_exits_zero_when_nothing_is_held(world, tmp_path, capsys) -> None:
    world.store.add(OJK, "run-1", write_bundle(tmp_path / "b1", [document()], run_id="run-1"))
    world.store.add(
        OJK, "run-2", write_bundle(tmp_path / "b2", [document("regalert:b")], run_id="run-2"), complete=False
    )

    assert cli.main(["load-pending", OJK]) == 0

    report = json.loads(capsys.readouterr().out)
    assert (report["loaded"], report["skipped"], report["held"], report["incomplete"]) == (1, 0, 0, 1)


def test_load_pending_exits_non_zero_when_it_held_a_bundle(world, tmp_path, capsys) -> None:
    world.store.add(OJK, "run-1", tmp_path / "no-such-bundle")

    assert cli.main(["load-pending", OJK]) == 1

    report = json.loads(capsys.readouterr().out)
    assert (report["loaded"], report["held"], report["failed_run"]) == (0, 1, "run-1")


def test_market_load_pending_loads_into_the_market_layer(world, tmp_path, capsys) -> None:
    world.store.add(
        REGISTER, "run-1", write_market_bundle(tmp_path / "b1", [licensed("KEP-1/D.05/2021", "2021-01-31")])
    )

    assert cli.main(["market", "load-pending", REGISTER]) == 0

    assert json.loads(capsys.readouterr().out)["loaded"] == 1
    assert ("ojk-register", "KEP-1/D.05/2021") in world.market.records


def test_upload_bundle_prints_where_the_bundle_went(world, tmp_path, capsys) -> None:
    directory = write_bundle(tmp_path / "out", [document()], run_id="20261124T020000")

    assert cli.main(["upload-bundle", str(directory), "s3://ops/bundles"]) == 0

    assert json.loads(capsys.readouterr().out) == {"location": f"{OJK}/20261124T020000"}


def test_upload_bundle_refuses_a_bundle_whose_export_did_not_finish(world, tmp_path, capsys) -> None:
    (tmp_path / "half").mkdir()

    assert cli.main(["upload-bundle", str(tmp_path / "half"), "s3://ops/bundles"]) == 1

    assert "refused" in capsys.readouterr().err


def test_an_expired_sign_in_exits_3_and_says_to_run_aws_sso_login(world, tmp_path, capsys, monkeypatch) -> None:
    def refused(directory, location):
        raise BundleStoreAuthenticationError("sign in again with `aws sso login`, then retry")

    monkeypatch.setattr(world.store, "upload", refused)
    directory = write_bundle(tmp_path / "out", [document()])

    assert cli.main(["upload-bundle", str(directory), "s3://ops/bundles"]) == cli.EXIT_NOT_SIGNED_IN == 3

    assert "aws sso login" in capsys.readouterr().err


def test_upload_bundle_needs_no_database_settings(world, tmp_path, monkeypatch) -> None:
    """The collection host has AWS credentials only."""
    monkeypatch.delenv("METAMORPH_DATABASE_URL")
    directory = write_bundle(tmp_path / "out", [document()])

    assert cli.main(["upload-bundle", str(directory), "s3://ops/bundles"]) == 0
