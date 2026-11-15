"""The published catalogue over HTTP: only a service client's token reads it, and it reads nothing else."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from metamorph_platform.adapters.api.accounts import Accounts, hash_password
from metamorph_platform.adapters.api.app import ApiServices, create_api
from metamorph_platform.adapters.api.clients import ServiceClients, new_token, sha256_of
from metamorph_platform.application.published_catalogue import (
    MOST_PER_PAGE,
    PAGE_SIZE,
    CatalogueEntry,
    CatalogueFacets,
    CatalogueFilters,
    CataloguePage,
    FacetCount,
    InvalidCursor,
)

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cr"
TOKEN = new_token()
ENTRY = CatalogueEntry(
    id="ojk:pojk:2020:47",
    citation="POJK 47/POJK.05/2020",
    title="PERIZINAN USAHA",
    kind="regulation",
    issuer="ojk",
    family="pojk",
    number="47",
    year=2020,
    status="in_force",
    promulgated_on=date(2020, 11, 25),
    effective_on=date(2020, 11, 26),
)


class MemoryCatalogue:
    def __init__(self) -> None:
        self.asked: list[tuple[CatalogueFilters, str | None, int]] = []

    def page(self, filters, cursor, limit):
        if cursor == "forged":
            raise InvalidCursor("this cursor wasn't given by the catalogue")
        self.asked.append((filters, cursor, limit))
        return CataloguePage(entries=(ENTRY,), total=1, next_cursor=None)

    def facets(self, filters):
        self.asked.append((filters, None, 0))
        return CatalogueFacets(
            total=1,
            issuers=(FacetCount("ojk", 1),),
            families=(FacetCount("pojk", 1),),
            years=(FacetCount("2020", 1),),
            statuses=(FacetCount("in_force", 1),),
            kinds=(FacetCount("regulation", 1),),
        )


@pytest.fixture
def world():
    catalogue = MemoryCatalogue()

    @contextmanager
    def services():
        yield ApiServices(
            views=None,
            curate=None,
            correct_text=None,
            add_manual=None,
            parse=None,
            publish=None,
            blobs=None,
            files=None,
            market_views=None,
            curate_market=None,
            published=catalogue,
        )

    curator = {"username": "ani", "name": "Ani", "password_hash": hash_password("rahasia", iterations=1_000)}
    accounts = Accounts.from_json(json.dumps([curator]))
    clients = ServiceClients.from_json(json.dumps([{"name": "mira", "token_sha256": sha256_of(TOKEN)}]))
    return TestClient(create_api(services, accounts, SECRET, clients=clients)), catalogue


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_a_client_reads_a_page_of_published_regulations(world):
    client, _ = world
    body = client.get("/api/v1/published/regulations", headers=bearer(TOKEN)).json()
    assert body["total"] == 1 and body["next_cursor"] is None
    assert body["entries"][0] == {
        "id": "ojk:pojk:2020:47",
        "citation": "POJK 47/POJK.05/2020",
        "title": "PERIZINAN USAHA",
        "kind": "regulation",
        "issuer": "ojk",
        "family": "pojk",
        "number": "47",
        "year": 2020,
        "status": "in_force",
        "promulgated_on": "2020-11-25",
        "effective_on": "2020-11-26",
    }


def test_filters_reach_the_catalogue_and_a_page_is_never_too_large(world):
    client, catalogue = world
    client.get(
        "/api/v1/published/regulations",
        headers=bearer(TOKEN),
        params={"q": " kepemilikan asing ", "issuer": "ojk", "year": 2020, "cursor": "abc", "limit": 1000},
    )
    filters, cursor, limit = catalogue.asked[-1]
    assert filters == CatalogueFilters("kepemilikan asing", "ojk", "", 2020, "", "")
    assert cursor == "abc" and limit == MOST_PER_PAGE
    client.get("/api/v1/published/regulations", headers=bearer(TOKEN))
    assert catalogue.asked[-1][2] == PAGE_SIZE


def test_a_client_reads_the_facets(world):
    client, catalogue = world
    body = client.get("/api/v1/published/facets", headers=bearer(TOKEN), params={"family": "pojk"}).json()
    assert body["issuers"] == [{"value": "ojk", "count": 1}] and body["years"][0]["value"] == "2020"
    assert catalogue.asked[-1][0] == replace(CatalogueFilters(), family="pojk")


def test_a_forged_cursor_is_invalid(world):
    client, _ = world
    answer = client.get("/api/v1/published/regulations", headers=bearer(TOKEN), params={"cursor": "forged"})
    assert answer.status_code == 422 and answer.json()["error"] == "invalid"


@pytest.mark.parametrize("headers", [{}, bearer(new_token()), {"Authorization": "Basic bWlyYTp4"}])
def test_without_a_clients_token_the_catalogue_is_closed(world, headers):
    client, catalogue = world
    answer = client.get("/api/v1/published/regulations", headers=headers)
    assert answer.status_code == 401 and answer.json()["error"] == "unauthorized"
    assert catalogue.asked == []


def test_a_curators_session_does_not_open_the_catalogue(world):
    client, _ = world
    session = client.post("/api/v1/auth/session", json={"username": "ani", "password": "rahasia"}).json()
    assert client.get("/api/v1/published/regulations", headers=bearer(session["token"])).status_code == 401


def test_a_clients_token_does_not_open_curation(world):
    client, _ = world
    assert client.get("/api/v1/overview", headers=bearer(TOKEN)).status_code == 401
    assert (
        client.post(
            "/api/v1/documents/ojk:pojk:2020:47/suppression", headers=bearer(TOKEN), json={"reason": "x"}
        ).status_code
        == 401
    )
