"""The composition root: the only module that knows which adapter implements which port."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from metamorph_platform.adapters.api.accounts import Accounts
from metamorph_platform.adapters.api.app import ApiServices, create_api
from metamorph_platform.adapters.api.app import ServicesFactory as ApiServicesFactory
from metamorph_platform.adapters.blobs.s3 import S3BlobStore, S3FileLinks
from metamorph_platform.adapters.postgres.curation import PostgresCurationActions, PostgresOverrides
from metamorph_platform.adapters.postgres.derived import PostgresCitationLinks, PostgresParsedTexts, PostgresValidity
from metamorph_platform.adapters.postgres.health import PostgresHealth
from metamorph_platform.adapters.postgres.loading import PostgresIngestLedger, PostgresRegistry, PostgresReviewQueue
from metamorph_platform.adapters.postgres.market import PostgresMarket, PostgresPublishedMarket
from metamorph_platform.adapters.postgres.market_curation import PostgresMarketCuration
from metamorph_platform.adapters.postgres.market_views import PostgresMarketViews
from metamorph_platform.adapters.postgres.publishing import PostgresPublication
from metamorph_platform.adapters.postgres.reviews import PostgresOpenReviews
from metamorph_platform.adapters.postgres.views import PostgresCurationViews
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.check_health import CheckHealth
from metamorph_platform.application.compute_validity import ComputeValidity
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.curate_market import CurateMarket
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.load_market_bundle import LoadMarketBundle
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.publish_market import PublishMarket
from metamorph_platform.application.relink_market import RelinkMarket
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


def load_market_bundle(connection: psycopg.Connection, settings: Settings) -> LoadMarketBundle:
    return LoadMarketBundle(
        ledger=PostgresIngestLedger(connection),
        market=PostgresMarket(connection),
        blobs=blob_store(settings),
        reviews=PostgresReviewQueue(connection),
    )


def publish_market(connection: psycopg.Connection, settings: Settings) -> PublishMarket:
    return PublishMarket(
        source=PostgresMarket(connection), published=PostgresPublishedMarket(connection), blobs=blob_store(settings)
    )


def relink_market(connection: psycopg.Connection) -> RelinkMarket:
    return RelinkMarket(source=PostgresMarket(connection), published=PostgresPublishedMarket(connection))


def curate_market(connection: psycopg.Connection) -> CurateMarket:
    curation = PostgresMarketCuration(connection)
    return CurateMarket(actions=curation, published=curation, relink=relink_market(connection))


def publish(connection: psycopg.Connection, settings: Settings) -> Publish:
    publication = PostgresPublication(connection)
    return Publish(source=publication, published=publication, texts=blob_store(settings), holds=publication)


def parse_texts(connection: psycopg.Connection, settings: Settings) -> ParseTexts:
    return ParseTexts(PostgresParsedTexts(connection), blob_store(settings))


def resolve_citations(connection: psycopg.Connection) -> ResolveCitations:
    return ResolveCitations(PostgresCitationLinks(connection), PostgresReviewQueue(connection))


def settle_reviews(connection: psycopg.Connection) -> SettleReviews:
    return SettleReviews(PostgresOpenReviews(connection))


def compute_validity(connection: psycopg.Connection) -> ComputeValidity:
    return ComputeValidity(PostgresValidity(connection))


def check_health(connection: psycopg.Connection) -> CheckHealth:
    return CheckHealth(PostgresHealth(connection))


def api_services(settings: Settings) -> ApiServicesFactory:
    """One connection per request, as for the HTML app."""

    @contextmanager
    def open_services() -> Iterator[ApiServices]:
        with connect(settings) as connection:
            views, actions, blobs = (
                PostgresCurationViews(connection),
                PostgresCurationActions(connection),
                blob_store(settings),
            )
            yield ApiServices(
                views=views,
                curate=Curate(actions),
                correct_text=CorrectText(actions, actions, blobs, blobs),
                add_manual=AddManualDocument(load_bundle(connection, settings), actions, known=views.exists),
                parse=parse_texts(connection, settings),
                publish=publish(connection, settings),
                blobs=blobs,
                files=file_links(settings),
                market_views=PostgresMarketViews(connection),
                curate_market=curate_market(connection),
            )

    return open_services


def file_links(settings: Settings) -> S3FileLinks:
    return S3FileLinks(
        settings.s3_bucket, settings.s3_endpoint_url, public_endpoint_url=settings.s3_public_endpoint_url
    )


def api_app(settings: Settings):
    curators, secret = settings.require_curation()
    return create_api(api_services(settings), Accounts.from_json(curators), secret)
