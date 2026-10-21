"""The curation JSON API against in-memory services: sign-in, reads, actions, and the shape of its errors."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from curation_samples import (
    DOC,
    FIXED_TEXT,
    GAPPY_SHA,
    GAPPY_TEXT,
    TEXT_SHA,
    CountingParse,
    CountingPublish,
    MemoryViews,
)
from fakes import (
    MemoryBlobReader,
    MemoryBlobStore,
    MemoryCorrectableTexts,
    MemoryCurationActions,
    MemoryLedger,
    MemoryOverrides,
    MemoryRegistry,
    MemoryReviewQueue,
)
from fastapi.testclient import TestClient

from metamorph_platform.adapters.api.accounts import Accounts, hash_password
from metamorph_platform.adapters.api.app import ApiServices, create_api
from metamorph_platform.adapters.api.tokens import TOKEN_LIFETIME
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import CorrectableText

SECRET = "s3cret-s3cret-s3cret-s3cret-s3cr"
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


class MemoryFileLinks:
    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}

    def uploaded(self, key: str) -> bytes | None:
        return self.uploads.get(key)

    def download_url(self, storage_key: str, *, name: str, media_type: str) -> str:
        return f"https://s3.test/{storage_key}?name={name}"

    def upload_url(self, key: str, *, media_type: str) -> str:
        return f"https://s3.test/{key}?upload"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(scope="module")
def accounts() -> Accounts:
    entry = {"username": "ani", "name": "Ani Rahma", "password_hash": hash_password("rahasia", iterations=1_000)}
    return Accounts.from_json(json.dumps([entry]))


@pytest.fixture
def world(accounts):
    actions, blobs, clock = MemoryCurationActions(), MemoryBlobStore(), Clock()
    blobs.put("gappy", GAPPY_TEXT.encode(), "text/markdown")
    correctable = MemoryCorrectableTexts({(DOC, GAPPY_SHA): CorrectableText("blobs/bb/gappy", paged=False)})
    load = LoadBundle(MemoryLedger(), MemoryRegistry(), blobs, MemoryReviewQueue(), MemoryOverrides())
    views = MemoryViews()
    services = ApiServices(
        views=views,
        curate=Curate(actions),
        correct_text=CorrectText(actions, correctable, blobs, blobs),
        add_manual=AddManualDocument(load, actions, known=lambda document_id: False),  # nothing is held yet
        parse=CountingParse(),
        publish=CountingPublish(),
        blobs=MemoryBlobReader({"blobs/bb/gappy": GAPPY_TEXT.encode(), "blobs/cc/fixed": FIXED_TEXT.encode()}),
        files=MemoryFileLinks(),
    )

    @contextmanager
    def open_services():
        yield services

    client = TestClient(create_api(open_services, accounts, SECRET, clock=clock))
    client.registry = load.registry  # so a test can see what an added document loaded
    return client, actions, services, clock


def signed_in(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/session", json={"username": "ani", "password": "rahasia"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_signing_in_returns_a_token_naming_the_curator(world) -> None:
    client = world[0]

    response = client.post("/api/v1/auth/session", json={"username": "ani", "password": "rahasia"})

    assert response.status_code == 200
    body = response.json()
    assert body["curator"] == {"username": "ani", "display_name": "Ani Rahma"}
    assert body["expires_at"] == (NOW + TOKEN_LIFETIME).isoformat().replace("+00:00", "Z")
    assert client.get("/api/v1/auth/session", headers=signed_in(client)).json()["username"] == "ani"


def test_a_wrong_password_is_refused_without_saying_which_part_was_wrong(world) -> None:
    response = world[0].post("/api/v1/auth/session", json={"username": "ani", "password": "salah"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "the username or password is wrong"}


def test_every_api_route_needs_a_valid_unexpired_token(world) -> None:
    client, _, _, clock = world
    headers = signed_in(client)

    assert client.get("/api/v1/overview").status_code == 401
    assert client.get("/api/v1/overview", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert client.get("/api/v1/overview", headers=headers).status_code == 200
    clock.now = NOW + TOKEN_LIFETIME
    assert client.get("/api/v1/overview", headers=headers).json()["error"] == "unauthorized"
    assert client.get("/healthz").text == "ok"


def get(client: TestClient, path: str, **params: str):
    return client.get(f"/api/v1{path}", params=params or None, headers=signed_in(client))


def test_the_overview_and_the_held_list_are_the_curation_read_models(world) -> None:
    client = world[0]

    assert get(client, "/overview").json()["held"] == 95
    held = get(client, "/held").json()
    assert held["rows"][0]["document_id"] == DOC
    assert held["rows"][0]["reasons"] == [{"check": "structure", "detail": "Pasal 3 missing"}]
    assert get(client, "/held?check=text").json()["rows"] == []
    assert get(client, "/held?check=nonsense").json() == {"error": "not_found", "message": "no check nonsense"}


def test_the_review_queues_and_search(world) -> None:
    client = world[0]

    assert get(client, "/reviews?kind=unresolved_citation").json()["total"] == 1
    assert get(client, "/reviews?kind=structure_suspect").status_code == 404
    assert [row["id"] for row in get(client, "/documents?q=10/POJK").json()["documents"]] == [DOC]
    assert get(client, "/documents?q=zzz").json()["documents"] == []


def test_search_lists_documents_or_articles_filtered_and_refuses_a_kind_it_does_not_know(world) -> None:
    client = world[0]

    articles = get(client, "/documents", q="satu", kind="articles", year="2019").json()
    assert [(hit["address"], hit["excerpt"]) for hit in articles["articles"]] == [("pasal-1", "«Satu».")]
    assert articles["filters"]["year"] == 2019 and articles["facets"][0]["name"] == "issuer"
    assert [hit["state"] for hit in get(client, "/documents").json()["documents"]] == ["held"]  # every document
    assert get(client, "/documents", kind="everything").status_code == 404
    assert get(client, "/documents", state="lost").status_code == 404


def test_browsing_lists_each_series_and_a_series_by_year(world) -> None:
    client = world[0]

    assert get(client, "/series").json() == [
        {"issuer": "ojk", "family": "pojk", "documents": 602, "first_year": 2013, "last_year": 2026}
    ]
    page = get(client, "/series/ojk/pojk", year="2019").json()
    assert (page["year"], [d["number"] for d in page["documents"]]) == (2019, ["10"])
    assert get(client, "/series/ojk/fatwa").status_code == 404


def test_a_document_reads_as_its_full_view_and_a_missing_one_is_404(world) -> None:
    client = world[0]

    view = get(client, f"/documents/{DOC}").json()

    assert view["summary"]["id"] == DOC and view["hold"][0]["check"] == "structure"
    assert [text["editable"] for text in view["texts"]] == [False, True, True]
    assert get(client, "/documents/ojk:pojk:1999:1").status_code == 404


def test_a_text_to_correct_comes_with_its_current_wording(world) -> None:
    client = world[0]

    body = get(client, f"/documents/{DOC}/texts/{GAPPY_SHA}/editable").json()

    assert body["text"]["sha256"] == GAPPY_SHA and body["wording"] == GAPPY_TEXT
    assert get(client, f"/documents/{DOC}/texts/{'f' * 64}/editable").status_code == 404


def test_a_correction_comes_with_both_wordings_and_the_diff(world) -> None:
    client = world[0]

    body = get(client, f"/documents/{DOC}/texts/{'c' * 64}/correction").json()

    assert body["correction"]["note"]["reason"] == "PDF hal. 4"
    assert (body["source"], body["corrected"]) == (GAPPY_TEXT, FIXED_TEXT)
    assert "+Pasal 2" in body["diff"]
    assert get(client, f"/documents/{DOC}/texts/{'f' * 64}/correction").status_code == 404


def test_a_text_reads_as_the_parser_cut_it_with_its_outline_and_a_missing_one_is_404(world) -> None:
    client = world[0]

    body = get(client, f"/documents/{DOC}/reading", at="pasal-3").json()

    assert (body["sha256"], body["part"], body["parts"]) == (GAPPY_SHA, 0, 1)
    assert [p["address"] for p in body["provisions"]] == ["pasal-1", "pasal-3"]
    block = {"marker": None, "depth": 0, "pages": [], "references": []}
    assert body["passages"] == [
        {"address": "pasal-1", "opens": True, "titled": True, "blocks": [{**block, "text": "Satu."}]},
        {"address": "pasal-3", "opens": True, "titled": True, "blocks": [{**block, "text": "Tiga."}]},
    ]
    assert get(client, f"/documents/{DOC}/reading", text="f" * 64).status_code == 404
    assert get(client, "/documents/ojk:pojk:1999:1/reading").status_code == 404


def test_a_file_or_text_is_opened_through_a_short_lived_link(world) -> None:
    client = world[0]

    body = get(client, f"/documents/{DOC}/content/{TEXT_SHA}").json()

    assert body == {"url": "https://s3.test/blobs/aa/text?name=id-aaaa.md"}
    assert get(client, f"/documents/{DOC}/content/{'b' * 64}").status_code == 404


def post(client: TestClient, path: str, body: dict):
    return client.post(f"/api/v1{path}", json=body, headers=signed_in(client))


@pytest.mark.parametrize(
    ("path", "body", "action"),
    [
        (f"/documents/{DOC}/corrections", {"field": "effective_on", "value": "2019-02-27"}, "correct"),
        (f"/documents/{DOC}/corrections/effective_on/withdraw", {}, "withdraw_correction"),
        (f"/documents/{DOC}/texts/{GAPPY_SHA}/approval", {}, "approve"),
        (f"/documents/{DOC}/texts/{GAPPY_SHA}/approval/withdraw", {}, "withdraw_approval"),
        (f"/documents/{DOC}/texts/{GAPPY_SHA}/correction", {"wording": FIXED_TEXT}, "correct_text"),
        (f"/documents/{DOC}/texts/{GAPPY_SHA}/correction/withdraw", {}, "withdraw_text_correction"),
        (f"/documents/{DOC}/suppression", {"confirm": True}, "suppress"),
        (f"/documents/{DOC}/restore", {}, "restore"),
        (f"/documents/{DOC}/id", {"new_id": DOC.upper()}, "assign_id"),
        (f"/documents/{DOC}/citations/88/link", {"target_id": "id:uu:2011:21"}, "link_citation"),
        (f"/documents/{DOC}/conflicts/7", {"decision": "keep"}, "resolve_conflict"),
    ],
)
def test_each_action_runs_its_use_case_then_parses_publishes_and_answers_the_documents_state(
    world, path, body, action
) -> None:
    client, actions, services, _ = world

    response = post(client, path, {**body, "reason": "  Lembaran Negara 2019/40 "})

    assert response.status_code == 200, response.json()
    assert response.json()["summary"]["id"] == DOC
    [(curator, recorded, _, _, reason)] = actions.calls
    assert (curator.username, recorded, reason) == ("ani", action, "Lembaran Negara 2019/40")
    assert (services.parse.runs, services.publish.runs) == (1, 1)


def test_a_review_decision_answers_what_was_decided(world) -> None:
    client, actions, services, _ = world

    response = post(client, "/reviews/12", {"state": "dismissed", "reason": "Halaman web, bukan peraturan"})

    assert response.json() == {"done": "dismissed"}
    assert actions.calls[0][1] == "decide_review" and services.publish.runs == 1


def test_what_a_curator_entered_but_cannot_apply_is_a_422_and_nothing_is_written(world) -> None:
    client, actions, services, _ = world

    bad_date = post(
        client, f"/documents/{DOC}/corrections", {"field": "effective_on", "value": "27/02/2019", "reason": "x"}
    )
    no_reason = post(client, f"/documents/{DOC}/restore", {"reason": " "})
    unconfirmed = post(client, f"/documents/{DOC}/suppression", {"reason": "Duplikat"})

    assert bad_date.status_code == no_reason.status_code == unconfirmed.status_code == 422
    assert bad_date.json()["error"] == "invalid" and "YYYY-MM-DD" in bad_date.json()["message"]
    assert "reason" in no_reason.json()["message"] and "confirm" in unconfirmed.json()["message"]
    assert actions.calls == [] and services.publish.runs == 0


def test_an_action_that_cannot_apply_as_asked_is_a_409(world) -> None:
    client, actions, _, _ = world

    response = post(client, f"/documents/{DOC}/texts/{'f' * 64}/correction", {"wording": "Pasal 1", "reason": "x"})

    assert response.status_code == 409
    assert response.json() == {"error": "refused", "message": f"{'f' * 12} isn't a current main text of {DOC}"}
    assert actions.calls == []


MANUAL = {
    "document_id": "ojk:pojk:2019:10",
    "citation": "POJK 10/POJK.05/2019",
    "title": "Penyelenggaraan Usaha Pembiayaan Syariah",
    "kind": "regulation",
    "status": "in_force",
    "language": "id",
    "source_url": "https://ojk.go.id/pojk-10-2019.pdf",
    "reason": "Belum ada di sumber mana pun",
    "rights": "public",
    "file_name": "pojk-10-2019.pdf",
    "media_type": "application/pdf",
}


def test_a_file_is_uploaded_straight_to_the_object_store_under_a_fresh_key(world) -> None:
    client = world[0]

    first = post(client, "/uploads", {"file_name": "pojk.pdf", "media_type": "application/pdf"}).json()
    second = post(client, "/uploads", {"file_name": "pojk.pdf", "media_type": "application/pdf"}).json()

    assert first["upload_key"].startswith("uploads/") and first["upload_key"] != second["upload_key"]
    assert first["url"] == f"https://s3.test/{first['upload_key']}?upload"


def test_a_document_is_added_from_its_uploaded_file_and_published(world) -> None:
    client, _, services, _ = world
    key = post(client, "/uploads", {"file_name": "pojk.pdf", "media_type": "application/pdf"}).json()["upload_key"]
    services.files.uploads[key] = b"%PDF-1.7 POJK 10/2019"

    response = post(client, "/documents", {**MANUAL, "upload_key": key})

    assert response.status_code == 200 and response.json()["summary"]["id"] == DOC
    assert ("manual", "manual:ojk:pojk:2019:10") in client.registry.records
    assert services.publish.runs == 1


def test_a_document_without_its_uploaded_file_or_with_bad_fields_says_what_to_fix_per_field(world) -> None:
    client = world[0]

    no_file = post(client, "/documents", {**MANUAL, "upload_key": "uploads/never-uploaded"})
    elsewhere = post(client, "/documents", {**MANUAL, "upload_key": "blobs/aa/someone-elses"})
    bad = post(client, "/documents", {**MANUAL, "source_url": "", "upload_key": "uploads/never-uploaded"})

    assert no_file.status_code == elsewhere.status_code == bad.status_code == 422
    assert "file" in no_file.json()["fields"] and "file" in elsewhere.json()["fields"]
    assert set(bad.json()["fields"]) == {"source_url", "file"}
