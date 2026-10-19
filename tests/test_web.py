"""The curation web app against in-memory services: sign-in, pages, changes, and their failure paths."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
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

from metamorph_platform.adapters.web.accounts import Accounts, hash_password
from metamorph_platform.adapters.web.app import WebServices, create_app
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.load_bundle import LoadBundle
from metamorph_platform.application.ports import CorrectableText
from metamorph_platform.application.views import (
    CheckRow,
    CitationRow,
    ContentRow,
    CorrectionView,
    CuratorNote,
    Dashboard,
    DocumentRow,
    DocumentView,
    EditableText,
    FieldRow,
    HeldPage,
    HeldRow,
    ReviewPage,
    ReviewRow,
    SourceRow,
    StoredBytes,
)
from metamorph_platform.domain.gate import Check, HoldReason

NOW = datetime(2026, 10, 15, 4, 36, tzinfo=UTC)
DOC = "ojk:pojk:2019:10"
ROW = DocumentRow(
    DOC,
    "POJK 10/POJK.05/2019",
    "Penyelenggaraan Usaha Pembiayaan Syariah",
    "ojk",
    "regulation",
    "in_force",
    suppressed=False,
)
TEXT_SHA = "a" * 64
GAPPY_SHA = "b" * 64
GAP = HoldReason(Check.STRUCTURE, "Pasal 3 missing")
GAPPY_TEXT = "Pasal 1\nSatu.\nPasal 3\nTiga.\n"
FIXED_TEXT = "Pasal 1\nSatu.\nPasal 2\nDua.\nPasal 3\nTiga.\n"


class MemoryViews:
    def dashboard(self) -> Dashboard:
        return Dashboard(
            "ok",
            NOW,
            (CheckRow("ojk", "ok", "last loaded 2 h ago (every 24 h)"),),
            (("ojk", 973),),
            2524,
            (("unresolved_citation", 235), ("conflict", 0)),
            (),
            held=95,
            held_published=4,
        )

    def held_page(self, check: str | None, page: int) -> HeldPage:
        rows = (HeldRow(DOC, ROW.title, (GAP,), published_at=NOW, held_since=NOW),)
        counts = tuple((c.value, 1 if c is Check.STRUCTURE else 0) for c in Check)
        shown = rows if check in (None, "structure") else ()
        return HeldPage(check, shown, counts, len(shown), 1, 1)

    def review_page(self, kind: str, page: int) -> ReviewPage:
        summary = "Keputusan Presiden Nomor 84/P"
        rows = (ReviewRow(12, kind, NOW, DOC, ROW.title, summary, {"document_id": DOC, "target_text": summary}),)
        citations = kind == "unresolved_citation"
        return ReviewPage(kind, rows if citations else (), 1 if citations else 0, 1, 1)

    def search(self, query: str, limit: int) -> list[DocumentRow]:
        return [ROW] if "10" in query else []

    def document(self, document_id: str) -> DocumentView | None:
        if document_id != DOC:
            return None
        fields = (FieldRow("effective_on", date(2019, 2, 27), None, (("ojk", None),), None),)
        sources = (SourceRow("ojk", "regalert:abc", "https://regalert.today/document/abc", NOW, None),)
        return DocumentView(
            ROW,
            "high",
            fields,
            None,
            sources,
            (),
            (
                ContentRow(TEXT_SHA, "id", "text/markdown", "source text"),
                ContentRow(GAPPY_SHA, "id", "text/markdown", "source text", ("Pasal 3 missing",), editable=True),
                ContentRow(
                    "c" * 64,
                    "id",
                    "text/markdown",
                    "source text",
                    ("Pasal 9 missing",),
                    CuratorNote("Pasal 9 dicabut", "ani", NOW),
                    correction=CuratorNote("PDF hal. 4", "ani", NOW),
                    editable=True,
                ),
            ),
            (),
            0,
            (),
            (),
            (CitationRow(88, "legal_basis", "Undang-Undang Nomor 21 Tahun 2011", None, None),),
            (),
            (),
            (),
            hold=(GAP,),
            published_at=NOW,
            lapsed_corrections=("d" * 64,),
        )

    def editable_text(self, document_id: str, sha256: str) -> EditableText | None:
        if (document_id, sha256) != (DOC, GAPPY_SHA):
            return None
        return EditableText(DOC, ROW.citation, GAPPY_SHA, "blobs/bb/gappy", paged=False, corrected=False)

    def correction(self, document_id: str, sha256: str) -> CorrectionView | None:
        if sha256 != "c" * 64:
            return None
        return CorrectionView(DOC, ROW.citation, sha256, "blobs/bb/gappy", "blobs/cc/fixed",
                              CuratorNote("PDF hal. 4", "ani", NOW), active=True, current=True)  # fmt: skip

    def stored(self, document_id: str, sha256: str) -> StoredBytes | None:
        return (
            StoredBytes("blobs/aa/text", "text/markdown; charset=utf-8", "id-aaaa.md") if sha256 == TEXT_SHA else None
        )

    def exists(self, document_id: str) -> bool:
        return document_id == DOC


class CountingParse:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, everything: bool = False):
        self.runs += 1


class CountingPublish:
    def __init__(self) -> None:
        self.runs = 0

    def run(self, *, everything: bool = False):
        self.runs += 1


@pytest.fixture(scope="module")
def accounts() -> Accounts:
    entry = {"username": "ani", "name": "Ani Rahma", "password_hash": hash_password("rahasia", iterations=1_000)}
    return Accounts.from_json(json.dumps([entry]))


@pytest.fixture
def world(accounts):
    actions, publish, registry, parse = MemoryCurationActions(), CountingPublish(), MemoryRegistry(), CountingParse()
    load = LoadBundle(MemoryLedger(), registry, MemoryBlobStore(), MemoryReviewQueue(), MemoryOverrides())
    views = MemoryViews()
    texts = MemoryBlobStore()
    texts.put("gappy", GAPPY_TEXT.encode(), "text/markdown")
    correctable = MemoryCorrectableTexts({(DOC, GAPPY_SHA): CorrectableText("blobs/bb/gappy", paged=False)})
    services = WebServices(
        views=views,
        curate=Curate(actions),
        add_manual=AddManualDocument(load, actions, known=views.exists),
        publish=publish,
        blobs=MemoryBlobReader(
            {
                "blobs/aa/text": b"<!-- page 1 -->\nPasal 1",
                "blobs/bb/gappy": GAPPY_TEXT.encode(),
                "blobs/cc/fixed": FIXED_TEXT.encode(),
            }
        ),
        correct_text=CorrectText(actions, correctable, texts, texts),
        parse=parse,
    )

    @contextmanager
    def open_services():
        yield services

    client = TestClient(create_app(open_services, accounts, secret="s3cret"))
    client.auth = ("ani", "rahasia")
    client.parse = parse  # so a test can see the immediate re-parse
    return client, actions, publish, registry


def token(client: TestClient) -> str:
    page = client.get(f"/documents/{DOC}").text
    return page.split('name="csrf" value="')[1].split('"')[0]


def test_every_page_needs_a_team_account(world, accounts) -> None:
    client = world[0]
    anonymous = TestClient(client.app)

    assert anonymous.get("/").status_code == 401
    assert anonymous.get("/", auth=("ani", "salah")).status_code == 401
    assert anonymous.get("/healthz").text == "ok"


def test_the_overview_shows_health_queues_and_the_registry(world) -> None:
    page = world[0].get("/").text

    assert "Ingestion Health" in page and "2,524" in page and "973" in page
    assert 'href="/review?kind=unresolved_citation"' in page
    assert 'href="/review?kind=structure_suspect"' not in page  # the publish gate holds those documents now
    assert "—" not in page and "–" not in page


def test_the_review_queue_lives_in_the_url_and_shows_an_empty_state(world) -> None:
    client = world[0]

    assert "Keputusan Presiden Nomor 84/P" in client.get("/review?kind=unresolved_citation").text
    assert "Nothing waits here" in client.get("/review?kind=conflict").text
    assert client.get("/review?kind=nonsense").status_code == 404
    assert client.get("/review?kind=structure_suspect").status_code == 404


def test_search_and_the_document_page(world) -> None:
    client = world[0]

    assert "POJK 10/POJK.05/2019" in client.get("/documents?q=10/POJK").text
    assert "No document matches" in client.get("/documents?q=zzz").text
    page = client.get(f"/documents/{DOC}").text
    assert "Correct a Field" in page and "Undang-Undang Nomor 21 Tahun 2011" in page
    assert client.get("/documents/ojk:pojk:1999:1").status_code == 404


def test_a_correction_is_recorded_published_and_redirected_with_a_notice(world) -> None:
    client, actions, publish, _ = world

    response = client.post(
        f"/documents/{DOC}/corrections",
        follow_redirects=False,
        data={
            "csrf": token(client),
            "field": "effective_on",
            "value": "2019-02-27",
            "reason": "Lembaran Negara 2019/40",
        },
    )

    assert response.status_code == 303 and response.headers["location"].endswith("?done=corrected#fields")
    assert actions.calls[0][1:4] == ("correct", {"document_id": DOC, "field": "effective_on"}, {"value": "2019-02-27"})
    assert publish.runs == 1
    assert "Correction saved and published." in client.get(response.headers["location"]).text


def test_a_bad_correction_shows_the_page_again_with_the_reason_beside_the_field(world) -> None:
    client, actions, publish, _ = world

    response = client.post(
        f"/documents/{DOC}/corrections",
        data={"csrf": token(client), "field": "effective_on", "value": "27/02/2019", "reason": "x"},
    )

    assert response.status_code == 422
    assert 'aria-invalid="true"' in response.text and "YYYY-MM-DD" in response.text
    assert actions.calls == [] and publish.runs == 0


def test_a_change_without_this_app_s_token_is_refused(world) -> None:
    client, actions, _, _ = world

    forged = client.post(f"/documents/{DOC}/suppress", data={"csrf": "x", "reason": "x", "confirm": "yes"})
    cross_site = client.post(
        f"/documents/{DOC}/suppress",
        headers={"origin": "https://evil.example"},
        data={"csrf": token(client), "reason": "x", "confirm": "yes"},
    )

    assert (forged.status_code, cross_site.status_code) == (403, 403)
    assert actions.calls == []


def test_suppressing_needs_an_explicit_confirmation(world) -> None:
    client, actions, _, _ = world

    response = client.post(f"/documents/{DOC}/suppress", data={"csrf": token(client), "reason": "Duplikat"})

    assert response.status_code == 422 and "tick the box" in response.text.lower()
    assert actions.calls == []


def test_a_review_decision_returns_to_the_queue_and_never_off_site(world) -> None:
    client, actions, _, _ = world

    response = client.post(
        "/review/12",
        follow_redirects=False,
        data={
            "csrf": token(client),
            "state": "dismissed",
            "note": "Halaman web, bukan peraturan",
            "back": "https://evil.example/review",
        },
    )

    assert response.headers["location"].startswith("/review?done=dismissed")
    assert actions.calls[0][1] == "decide_review"


def test_a_file_or_text_streams_with_its_media_type(world) -> None:
    client = world[0]

    response = client.get(f"/documents/{DOC}/content/{TEXT_SHA}")

    assert response.status_code == 200 and response.text.startswith("<!-- page 1 -->")
    assert response.headers["content-type"].startswith("text/markdown")
    assert client.get(f"/documents/{DOC}/content/{'b' * 64}").status_code == 404


def test_adding_a_document_reports_each_bad_field_and_loads_a_good_one(world) -> None:
    client, actions, publish, registry = world
    fields = {
        "document_id": "dsnmui:fatwa:170",
        "citation": "Fatwa DSN-MUI No. 170/DSN-MUI/X/2026",
        "title": "Pembiayaan Rumah Syariah",
        "kind": "fatwa",
        "status": "in_force",
        "language": "id",
        "source_url": "https://dsnmui.or.id/kategori/fatwa/",
        "reason": "Terbit setelah sync",
        "rights": "public",
    }

    refused = client.post(
        "/documents/new",
        data={**fields, "csrf": token(client), "source_url": ""},
        files={"file": ("fatwa-170.pdf", b"%PDF-1.7", "application/pdf")},
    )
    added = client.post(
        "/documents/new",
        follow_redirects=False,
        data={**fields, "csrf": token(client)},
        files={"file": ("fatwa-170.pdf", b"%PDF-1.7", "application/pdf")},
    )

    assert refused.status_code == 422 and 'id="source_url-error"' in refused.text
    assert added.status_code == 303 and added.headers["location"] == "/documents/dsnmui%3Afatwa%3A170?done=added"
    assert ("manual", "manual:dsnmui:fatwa:170") in registry.records
    assert publish.runs == 1


def test_dates_are_machine_readable_and_never_escaped(world) -> None:
    page = world[0].get(f"/documents/{DOC}").text

    assert '<time datetime="2019-02-27">27 Feb 2019</time>' in page
    assert "&lt;time" not in page


def test_the_overview_counts_the_held_documents_and_links_to_them(world) -> None:
    page = world[0].get("/").text

    assert 'href="/held"' in page and "95" in page


def test_the_held_list_says_why_each_document_is_held_and_filters_by_check(world) -> None:
    client = world[0]

    page = client.get("/held").text
    assert DOC in page and "Pasal 3 missing" in page
    assert "Last published" in page and "15 Oct 2026" in page
    assert "Nothing is held" in client.get("/held?check=text").text
    assert client.get("/held?check=nonsense").status_code == 404


def test_a_held_document_says_why_and_which_version_the_assistant_sees(world) -> None:
    page = world[0].get(f"/documents/{DOC}").text

    assert "Held back from publishing" in page and "Pasal 3 missing" in page
    assert "The assistant sees the version published on" in page


def test_a_text_with_problems_offers_approval_and_an_approved_one_its_withdrawal(world) -> None:
    page = world[0].get(f"/documents/{DOC}").text

    assert f'action="/documents/{DOC.replace(":", "%3A")}/texts/{GAPPY_SHA}/approve"' in page
    assert "Approved as is" in page and "Pasal 9 dicabut" in page
    assert f'/texts/{"c" * 64}/approve/withdraw"' in page


def test_approving_a_text_as_it_is_is_recorded_and_published(world) -> None:
    client, actions, publish, _ = world

    response = client.post(
        f"/documents/{DOC}/texts/{GAPPY_SHA}/approve",
        follow_redirects=False,
        data={"csrf": token(client), "reason": "Pasal 3 dicabut oleh POJK 12/2021"},
    )

    assert response.status_code == 303 and response.headers["location"].endswith("?done=approved#content")
    assert actions.calls[0][1:3] == ("approve", {"document_id": DOC, "text_sha256": GAPPY_SHA})
    assert publish.runs == 1
    assert (
        "Approved. The document is checked again and published if it passes."
        in client.get(response.headers["location"]).text
    )


def test_an_approval_without_a_reason_is_refused_beside_its_form(world) -> None:
    client, actions, publish, _ = world

    response = client.post(f"/documents/{DOC}/texts/{GAPPY_SHA}/approve", data={"csrf": token(client), "reason": ""})

    assert response.status_code == 422 and "reason" in response.text
    assert actions.calls == [] and publish.runs == 0


def test_withdrawing_an_approval_is_recorded_and_published(world) -> None:
    client, actions, publish, _ = world

    client.post(
        f"/documents/{DOC}/texts/{'c' * 64}/approve/withdraw",
        data={"csrf": token(client), "reason": "Pasal 9 ada di PDF"},
    )

    assert actions.calls[0][1] == "withdraw_approval" and publish.runs == 1


def test_the_edit_page_shows_the_texts_current_wording_to_correct(world) -> None:
    client = world[0]

    page = client.get(f"/documents/{DOC}/texts/{GAPPY_SHA}/edit").text

    assert "<textarea" in page and "Pasal 3\nTiga." in page and 'name="reason"' in page
    assert client.get(f"/documents/{DOC}/texts/{'f' * 64}/edit").status_code == 404


def test_a_corrected_text_is_recorded_parsed_and_published_at_once(world) -> None:
    client, actions, publish, _ = world

    response = client.post(
        f"/documents/{DOC}/texts/{GAPPY_SHA}/correction",
        follow_redirects=False,
        data={"csrf": token(client), "wording": FIXED_TEXT, "reason": "PDF hal. 2"},
    )

    assert response.status_code == 303 and response.headers["location"].endswith("?done=text_corrected#content")
    assert actions.calls[0][1:3] == ("correct_text", {"document_id": DOC, "text_sha256": GAPPY_SHA})
    assert (client.parse.runs, publish.runs) == (1, 1)


def test_a_bad_correction_shows_the_edit_page_again_keeping_what_was_typed(world) -> None:
    client, actions, publish, _ = world

    response = client.post(
        f"/documents/{DOC}/texts/{GAPPY_SHA}/correction",
        data={"csrf": token(client), "wording": GAPPY_TEXT, "reason": "PDF hal. 2"},
    )

    assert response.status_code == 422 and "unchanged" in response.text and "Pasal 3\nTiga." in response.text
    assert actions.calls == [] and publish.runs == 0


def test_a_text_correction_is_withdrawn_from_the_document_page(world) -> None:
    client, actions, publish, _ = world

    client.post(
        f"/documents/{DOC}/texts/{'c' * 64}/correction/withdraw",
        data={"csrf": token(client), "reason": "Sumber sudah benar"},
    )

    assert actions.calls[0][1] == "withdraw_text_correction" and publish.runs == 1


def test_the_document_page_links_each_main_text_to_its_editor_and_its_correction(world) -> None:
    page = world[0].get(f"/documents/{DOC}").text
    here = f"/documents/{DOC.replace(':', '%3A')}"

    assert f'href="{here}/texts/{GAPPY_SHA}/edit"' in page
    assert "Corrected by ani" in page and f'href="{here}/texts/{"c" * 64}/correction"' in page
    assert "no longer applies" in page and f'href="{here}/texts/{"d" * 64}/correction"' in page


def test_the_correction_page_shows_what_the_curator_changed(world) -> None:
    client = world[0]

    page = client.get(f"/documents/{DOC}/texts/{'c' * 64}/correction").text

    assert "+Pasal 2" in page and "PDF hal. 4" in page
    assert client.get(f"/documents/{DOC}/texts/{'f' * 64}/correction").status_code == 404
