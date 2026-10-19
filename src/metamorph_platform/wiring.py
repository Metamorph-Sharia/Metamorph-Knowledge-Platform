"""The composition root: the only module that knows which adapter implements which port."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from metamorph_platform.adapters.blobs.s3 import S3BlobStore
from metamorph_platform.adapters.postgres.curation import PostgresCurationActions, PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks, PostgresParsedTexts, PostgresValidity
from metamorph_platform.adapters.postgres.health import PostgresHealth
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.adapters.postgres.reviews import PostgresOpenReviews
from metamorph_platform.adapters.postgres.views import PostgresCurationViews
from metamorph_platform.adapters.web.accounts import Accounts
from metamorph_platform.adapters.web.app import ServicesFactory, WebServices, create_app
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.check_health import CheckHealth
from metamorph_platform.application.compute_validity import ComputeValidity
from metamorph_platform.application.curate import Curate
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.resolve_citations import ResolveCitations
from metamorph_platform.application.settle_reviews import SettleReviews
from metamorph_platform.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    """Autocommit: each adapter operation that must be atomic opens its own transaction."""
    return psycopg.connect(settings.database_url, autocommit=True)


def blob_store(settings: Settings) -> S3BlobStore:
    return S3BlobStore(settings.s3_bucket, settings.s3_endpoint_url)


def load_bundle(connection: psycopg.Connection, settings: Settings) -> LoadBundle:
    return LoadBundle(
        ledger=PostgresIngestLedger(connection),
        registry=PostgresRegistry(connection),
        blobs=blob_store(settings),
        reviews=PostgresReviewQueue(connection),
        overrides=PostgresOverrides(connection),
    )


def publish(connection: psycopg.Connection, settings: Settings) -> Publish:
    publication = PostgresPublication(connection)
    return Publish(source=publication, published=publication, texts=blob_store(settings))


def parse_texts(connection: psycopg.Connection, settings: Settings) -> ParseTexts:
    return ParseTexts(PostgresParsedTexts(connection), blob_store(settings), PostgresReviewQueue(connection))


def resolve_citations(connection: psycopg.Connection) -> ResolveCitations:
    return ResolveCitations(PostgresCitationLinks(connection), PostgresReviewQueue(connection))


def settle_reviews(connection: psycopg.Connection) -> SettleReviews:
    return SettleReviews(PostgresOpenReviews(connection))


def compute_validity(connection: psycopg.Connection) -> ComputeValidity:
    return ComputeValidity(PostgresValidity(connection))


def check_health(connection: psycopg.Connection) -> CheckHealth:
    return CheckHealth(PostgresHealth(connection))


def web_services(settings: Settings) -> ServicesFactory:
    """One connection per request: the app's threads never share one."""

    @contextmanager
    def open_services() -> Iterator[WebServices]:
        with connect(settings) as connection:
            views, actions = PostgresCurationViews(connection), PostgresCurationActions(connection)
            yield WebServices(
                views=views,
                curate=Curate(actions),
                add_manual=AddManualDocument(load_bundle(connection, settings), actions, known=views.exists),
                publish=publish(connection, settings),
                blobs=blob_store(settings),
            )

    return open_services


def web_app(settings: Settings):
    curators, secret = settings.require_web()
    return create_app(web_services(settings), Accounts.from_json(curators), secret)
