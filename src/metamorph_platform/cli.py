"""`metamorph …`: the platform's command line, for people and for Airflow tasks.

Exit codes: 0 ok · 1 refused (an edited migration, a bundle loaded before or unloadable) · 2 misconfigured.
`metamorph health` instead: 0 ok · 1 warning · 2 critical, like the connectors' own `health`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import metamorph_market
from metamorph_contract import Bundle, UnloadableBundle

from metamorph_platform import wiring
from metamorph_platform.adapters.postgres import migrate as migrations
from metamorph_platform.application.ports import BundleAlreadyLoaded
from metamorph_platform.config import ConfigurationError, Settings
from metamorph_platform.domain.health import Severity

EXIT_OK, EXIT_REFUSED, EXIT_MISCONFIGURED = 0, 1, 2
MIN_PASSWORD_LENGTH = 12
REFUSALS = (migrations.MigrationError, BundleAlreadyLoaded, UnloadableBundle, metamorph_market.UnloadableBundle)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        settings = Settings.from_environment() if getattr(arguments, "needs_settings", True) else None
        return arguments.run(settings, arguments)
    except ConfigurationError as error:
        print(f"configuration: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    except REFUSALS as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metamorph", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    database = commands.add_parser("db", help="database schema").add_subparsers(required=True, metavar="ACTION")
    database.add_parser("migrate", help="apply pending migrations").set_defaults(run=_migrate)
    database.add_parser("status", help="list applied and pending migrations").set_defaults(run=_status)

    storage = commands.add_parser("storage", help="object store").add_subparsers(required=True, metavar="ACTION")
    init = storage.add_parser("init", help="create the blob bucket if it doesn't exist")
    init.add_argument(
        "--upload-origin",
        action="append",
        default=[],
        metavar="URL",
        help="let browsers on this origin (the curation web app) upload files into the bucket; repeatable",
    )
    init.set_defaults(run=_storage_init)

    load = commands.add_parser("load", help="load a connector's contract v2 bundle into the registry")
    load.add_argument("bundle", type=Path, help="the bundle directory (manifest.json, documents.jsonl, blobs/)")
    load.add_argument("--publish", action="store_true", help="refresh `published` afterwards")
    load.set_defaults(run=_load)

    publish = commands.add_parser("publish", help="refresh `published` for documents that changed")
    publish.add_argument("--all", action="store_true", help="republish every document")
    publish.set_defaults(run=_publish)

    market = commands.add_parser("market", help="the market data layer: registers of licensed entities")
    market_actions = market.add_subparsers(required=True, metavar="ACTION")
    market_load = market_actions.add_parser("load", help="load a market connector's bundle (market contract)")
    market_load.add_argument("bundle", type=Path, help="the bundle directory (manifest.json, records.jsonl, blobs/)")
    market_load.add_argument("--publish", action="store_true", help="refresh `published_market` afterwards")
    market_load.set_defaults(run=_market_load)
    market_actions.add_parser("publish", help="rebuild `published_market` from the records held").set_defaults(
        run=_market_publish
    )

    parse = commands.add_parser("parse", help="parse new or changed texts: provisions, citations, stated dates")
    parse.add_argument("--all", action="store_true", help="parse every current text again")
    parse.set_defaults(run=_parse)
    commands.add_parser("resolve", help="link citations to the documents they name").set_defaults(run=_resolve)
    commands.add_parser("validity", help="status events and article end dates from links").set_defaults(run=_validity)
    commands.add_parser(
        "settle", help="resolve the citation items whose cause is gone; count those that need a person"
    ).set_defaults(run=_settle)
    build = commands.add_parser(
        "build", help="parse, resolve, settle reviews, validity, then publish: the registry build"
    )
    build.add_argument("--reparse", action="store_true", help="parse every current text again")
    build.set_defaults(run=_build)
    health = commands.add_parser("health", help="is ingestion healthy? exit 0 ok / 1 warning / 2 critical")
    health.add_argument(
        "--fail-on",
        choices=["warning", "critical"],
        default="warning",
        help="the least severe status that exits non-zero",
    )
    health.set_defaults(run=_health)

    api = commands.add_parser("api", help="serve the curation JSON API (/api/v1) for the curation web app")
    api.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    api.add_argument("--port", type=int, default=8001)
    api.set_defaults(run=_api)
    curator = commands.add_parser("curator", help="curation app accounts").add_subparsers(
        required=True, metavar="ACTION"
    )
    curator.add_parser(
        "hash-password", help="hash a password for METAMORPH_CURATORS (reads it without echo)"
    ).set_defaults(run=_hash_password, needs_settings=False)
    return parser


def _migrate(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        applied = migrations.migrate(connection)
    print(f"applied {len(applied)} migration(s)" + "".join(f"\n  {m.version:04d} {m.name}" for m in applied))
    return EXIT_OK


def _status(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        done = {m.version for m in migrations.applied(connection)}
    for migration in migrations.available():
        print(f"{'applied' if migration.version in done else 'pending':8} {migration.version:04d} {migration.name}")
    return EXIT_OK


def _storage_init(settings: Settings, arguments: argparse.Namespace) -> int:
    blobs = wiring.blob_store(settings)
    created = blobs.ensure_bucket()
    print(f"bucket {settings.s3_bucket}: {'created' if created else 'already there'}")
    if arguments.upload_origin:
        blobs.allow_uploads_from(arguments.upload_origin)
        print(f"uploads allowed from {', '.join(arguments.upload_origin)}")
    return EXIT_OK


def _load(settings: Settings, arguments: argparse.Namespace) -> int:
    bundle = Bundle(arguments.bundle)
    with wiring.connect(settings) as connection:
        report = wiring.load_bundle(connection, settings).run(bundle, uri=str(arguments.bundle.resolve()))
        result = {"bundle_id": report.bundle_id, "connector": report.connector, **report.counts()}
        if arguments.publish:
            result["published"] = wiring.publish(connection, settings).run().counts()
    print(json.dumps(result, indent=2))
    return EXIT_OK


def _publish(settings: Settings, arguments: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(wiring.publish(connection, settings).run(everything=arguments.all).counts(), indent=2))
    return EXIT_OK


def _market_load(settings: Settings, arguments: argparse.Namespace) -> int:
    bundle = metamorph_market.Bundle(arguments.bundle)
    with wiring.connect(settings) as connection:
        report = wiring.load_market_bundle(connection, settings).run(bundle, uri=str(arguments.bundle.resolve()))
        result = {"bundle_id": report.bundle_id, "connector": report.connector, **report.counts()}
        if arguments.publish:
            result["published"] = asdict(wiring.publish_market(connection).run())
    print(json.dumps(result, indent=2))
    return EXIT_OK


def _market_publish(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(asdict(wiring.publish_market(connection).run()), indent=2))
    return EXIT_OK


def _parse(settings: Settings, arguments: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(wiring.parse_texts(connection, settings).run(everything=arguments.all).counts(), indent=2))
    return EXIT_OK


def _resolve(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(wiring.resolve_citations(connection).run().counts(), indent=2))
    return EXIT_OK


def _settle(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(wiring.settle_reviews(connection).run().counts(), indent=2))
    return EXIT_OK


def _validity(settings: Settings, _: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        print(json.dumps(wiring.compute_validity(connection).run().counts(), indent=2))
    return EXIT_OK


def _build(settings: Settings, arguments: argparse.Namespace) -> int:
    """The order matters: links need the parsed citations, settling judges citation items on today's
    citations and links, validity needs the links, publish (and its gate) needs them all."""
    with wiring.connect(settings) as connection:
        result = {
            "parse": wiring.parse_texts(connection, settings).run(everything=arguments.reparse).counts(),
            "resolve": wiring.resolve_citations(connection).run().counts(),
            "reviews": wiring.settle_reviews(connection).run().counts(),
            "validity": wiring.compute_validity(connection).run().counts(),
            "publish": wiring.publish(connection, settings).run().counts(),
        }
    print(json.dumps(result, indent=2))
    return EXIT_OK


def _api(settings: Settings, arguments: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(wiring.api_app(settings), host=arguments.host, port=arguments.port, proxy_headers=True)
    return EXIT_OK


def _hash_password(_: None, __: argparse.Namespace) -> int:
    from getpass import getpass

    from metamorph_platform.adapters.api.accounts import hash_password

    password = getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH or password != getpass("Again: "):
        print(f"refused: passwords differ, or shorter than {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return EXIT_REFUSED
    print(hash_password(password))
    return EXIT_OK


HEALTH_EXIT = {Severity.OK: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


def health_exit(status: Severity, fail_on: Severity) -> int:
    return HEALTH_EXIT[status] if status.rank >= fail_on.rank else EXIT_OK


def _health(settings: Settings, arguments: argparse.Namespace) -> int:
    with wiring.connect(settings) as connection:
        health = wiring.check_health(connection).run()
    print(json.dumps({"status": health.status.value, "checks": [asdict(c) for c in health.checks]}, indent=2))
    return health_exit(health.status, Severity(arguments.fail_on))


if __name__ == "__main__":
    sys.exit(main())
