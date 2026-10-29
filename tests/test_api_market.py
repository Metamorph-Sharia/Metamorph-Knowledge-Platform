"""The curation API's market routes against in-memory services: the pages' reads, and changes to the curated links."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date

import pytest
from curation_samples import CountingParse, CountingPublish, MemoryViews
from fakes import MemoryBlobReader, MemoryBlobStore, MemoryCorrectableTexts, MemoryCurationActions
from fastapi.testclient import TestClient
from market_curation_samples import (
    BUS,
    COMPANY,
    DATASET,
    JournalledRelink,
    MemoryMarketCuration,
    MemoryMarketViews,
    MemoryPublishedNames,
)

from metamorph_platform.adapters.api.accounts import Accounts, hash_password
from metamorph_platform.adapters.api.app import ApiServices, create_api
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.curate_market import CurateMarket
from metamorph_platform.application.market_views import CompanyFilters, DatasetFilters

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cr"
API = "/api/v1/market"


@pytest.fixture
def world():
    accounts = Accounts.from_json(json.dumps(
        [{"username": "ani", "name": "Ani Rahma", "password_hash": hash_password("rahasia", iterations=1_000)}]))
    journal: list[str] = []
    actions, views = MemoryCurationActions(), MemoryMarketViews()
    services = ApiServices(
        views=MemoryViews(),
        curate=Curate(actions),
        correct_text=CorrectText(actions, MemoryCorrectableTexts({}), MemoryBlobStore(), MemoryBlobStore()),
        add_manual=None,
        parse=CountingParse(),
        publish=CountingPublish(),
        blobs=MemoryBlobReader({}),
        files=None,
        market_views=views,
        curate_market=CurateMarket(MemoryMarketCuration(journal), MemoryPublishedNames(), JournalledRelink(journal)),
    )

    @contextmanager
    def open_services():
        yield services

    client = TestClient(create_api(open_services, accounts, SECRET))
    token = client.post("/api/v1/auth/session", json={"username": "ani", "password": "rahasia"}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client, views, journal


def test_the_market_routes_need_a_signed_in_curator(world) -> None:
    client = world[0]

    assert TestClient(client.app).get(f"{API}/overview").status_code == 401
    assert client.get(f"{API}/overview").json()["counts"]["companies"] == 2


def test_lists_take_their_query_filters_and_page(world) -> None:
    client, views, _ = world

    companies = client.get(f"{API}/companies", params={"q": "bina", "status": "licensed", "page": 2}).json()
    client.get(f"{API}/datasets", params={"q": "kas", "industry": BUS})
    client.get(f"{API}/releases", params={"from": "2026-01-01"})

    assert companies["rows"][0]["legal_name"] == "PT Fintech Bina Bangsa"
    assert views.asked == [
        ("companies", "bina", CompanyFilters(status="licensed"), 2),
        ("datasets", "kas", DatasetFilters(industry=BUS), 1),
        ("releases", "", date(2026, 1, 1), None, 1),
    ]


def test_a_filter_outside_its_choices_and_an_unknown_record_are_not_found(world) -> None:
    client = world[0]

    assert client.get(f"{API}/companies", params={"status": "bankrupt"}).json() == {
        "error": "not_found", "message": "no company status bankrupt: licensed, registered or left"}
    assert client.get(f"{API}/companies/{COMPANY.id}").status_code == 200
    assert client.get(f"{API}/datasets/{DATASET.id}").json()["series_total"] == 2
    assert client.get(f"{API}/companies/nobody").json()["error"] == "not_found"
    assert client.get(f"{API}/series/gone").status_code == 404


def test_a_register_s_links_are_changed_published_and_answered_with_warnings_and_the_sources(world) -> None:
    client, _, journal = world

    response = client.put(f"{API}/registers/ojk:lpbbti/links", json={
        "governed_by": ["ojk:pojk:2024:40", "ojk:pojk:2026:9"], "reports": [], "fresh_days": 45,
        "reason": "POJK 9/2026 amends licensing"})

    assert response.status_code == 200
    assert response.json()["warnings"] == ["ojk:pojk:2026:9 is not published: it links nothing until it is"]
    assert response.json()["sources"]["sources"][0]["download_page"] == "https://www.bi.go.id/seki"
    assert journal[1:3] == ["register ojk:lpbbti ('ojk:pojk:2024:40', 'ojk:pojk:2026:9') by ani: POJK 9/2026 amends "
                            "licensing", "relink"]


def test_industries_sources_and_sectors_are_changed_by_their_own_routes(world) -> None:
    client, _, journal = world

    assert client.put(f"{API}/sources/ojk:portal/industries/{BUS}", json={
        "register": None, "governed_by": ["id:uu:2008:21"], "reports": [], "reason": "UU 21/2008"}).status_code == 200
    assert client.post(f"{API}/sources/ojk:portal/industries/{BUS}/withdraw", json={"reason": "renamed"}
                       ).status_code == 200
    assert client.put(f"{API}/sources/bi:seki", json={
        "citation": "BI, SEKI", "fresh_days": 90, "download_page": "", "download_hint": "", "reason": "shorter"}
    ).status_code == 200
    assert client.put(f"{API}/sectors/sharia-banking", json={
        "name": "Perbankan Syariah", "name_en": "Sharia banking", "industries": [{"source": "ojk:portal", "name": BUS}],
        "reason": "one list"}).status_code == 200
    assert client.post(f"{API}/sectors/sharia-banking/withdraw", json={"reason": "merged"}).status_code == 200

    assert [entry.split(":")[0] for entry in journal if entry not in ("begin", "relink", "commit")] == [
        "industry ojk", "withdraw industry ojk", "source bi", "sector sharia-banking 1",
        "withdraw sector sharia-banking"]


def test_a_change_that_cannot_apply_is_invalid_and_says_why(world) -> None:
    client, _, journal = world

    response = client.put(f"{API}/registers/ojk:lpbbti/links", json={
        "governed_by": ["POJK 40/2024"], "reports": [], "fresh_days": 45, "reason": "why"})

    assert response.status_code == 422
    assert response.json() == {"error": "invalid", "message": "POJK 40/2024 is not a document ID, such as "
                               "ojk:pojk:2024:40", "fields": {}}
    assert journal == []
