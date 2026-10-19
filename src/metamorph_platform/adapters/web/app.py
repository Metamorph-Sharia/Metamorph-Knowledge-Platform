"""The curation web app: server-rendered pages over the curation use cases and read views.

Every request opens its services (one database connection) for itself. Every change is a POST form with a
CSRF token, followed by a redirect (303). After it, what changed is parsed and published at once: the
curator sees whether the document now passes the publish gate, and the knowledge layer sees the result.
"""

# No `from __future__ import annotations`: FastAPI reads the dependency annotations at runtime, and these
# aliases (Who, Services, Token) are defined inside create_app, where string annotations can't find them.
import hashlib
import hmac
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from metamorph_platform.adapters.web import presentation
from metamorph_platform.adapters.web.accounts import Accounts
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import BlobReader, CurationRefused, Curator
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.views import HELD_CHECKS, REVIEW_KINDS, CurationViews
from metamorph_platform.domain.curation import InvalidCorrection
from metamorph_platform.domain.manual import InvalidManualDocument, ManualDocument

HERE = Path(__file__).parent
SEARCH_LIMIT = 50
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # UU 4/2023, the largest file we hold, is 82 MB


@dataclass
class WebServices:
    views: CurationViews
    curate: Curate
    add_manual: AddManualDocument
    publish: Publish
    blobs: BlobReader
    correct_text: CorrectText
    parse: ParseTexts  # only what changed: a corrected text


ServicesFactory = Callable[[], AbstractContextManager[WebServices]]


def create_app(open_services: ServicesFactory, accounts: Accounts, secret: str) -> FastAPI:
    app = FastAPI(title="Metamorph Curation", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    presentation.install(templates.env)
    basic = HTTPBasic(realm="Metamorph Curation")

    def curator(credentials: Annotated[HTTPBasicCredentials, Depends(basic)]) -> Curator:
        signed_in = accounts.verify(credentials.username, credentials.password)
        if signed_in is None:
            raise HTTPException(401, "Sign in with your team account.", {"WWW-Authenticate": 'Basic realm="Metamorph"'})
        return signed_in

    def services() -> Iterator[WebServices]:
        with open_services() as opened:
            yield opened

    def csrf_token(who: Curator) -> str:
        return hmac.new(secret.encode(), who.username.encode(), hashlib.sha256).hexdigest()

    def checked(request: Request, who: Curator, token: str) -> Curator:
        """A change must come from this app's own form: the token, and the browser's Origin when it sends one."""
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "This change didn't come from this app. Reload the page and try again.")
        if not hmac.compare_digest(token, csrf_token(who)):
            raise HTTPException(403, "This form expired. Reload the page and try again.")
        return who

    Who = Annotated[Curator, Depends(curator)]
    Services = Annotated[WebServices, Depends(services)]
    Token = Annotated[str, Form(alias="csrf")]

    def render(request: Request, who: Curator, template: str, status: int = 200, **context: Any) -> HTMLResponse:
        context |= {"curator": who, "csrf": csrf_token(who), "done": request.query_params.get("done")}
        return templates.TemplateResponse(request, template, context, status_code=status)

    def after_change(svc: WebServices, url: str, done: str) -> RedirectResponse:
        svc.parse.run()
        svc.publish.run()
        separator = "&" if "?" in url else "?"
        path, _, fragment = url.partition("#")
        return RedirectResponse(f"{path}{separator}done={done}" + (f"#{fragment}" if fragment else ""), status_code=303)

    def document_page(
        request: Request, who: Curator, svc: WebServices, document_id: str, status: int = 200, **context: Any
    ) -> HTMLResponse:
        view = svc.views.document(document_id)
        if view is None:
            return render(request, who, "missing.html", 404, what=f"No document {document_id}")
        return render(request, who, "document.html", status, view=view, **context)

    # --- pages ---------------------------------------------------------------------------------

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, who: Who, svc: Services) -> HTMLResponse:
        return render(request, who, "overview.html", dashboard=svc.views.dashboard())

    @app.get("/review", response_class=HTMLResponse)
    def review(
        request: Request, who: Who, svc: Services, kind: str = REVIEW_KINDS[0], page: int = 1, error: str | None = None
    ) -> HTMLResponse:
        if kind not in REVIEW_KINDS:
            return render(request, who, "missing.html", 404, what=f"No review queue {kind}")
        counts = dict(svc.views.dashboard().open_reviews)
        return render(request, who, "review.html", queue=svc.views.review_page(kind, page), counts=counts, error=error)

    @app.get("/held", response_class=HTMLResponse)
    def held(request: Request, who: Who, svc: Services, check: str = "", page: int = 1) -> HTMLResponse:
        if check and check not in HELD_CHECKS:
            return render(request, who, "missing.html", 404, what=f"No check {check}")
        return render(request, who, "held.html", held=svc.views.held_page(check or None, page))

    @app.get("/documents", response_class=HTMLResponse)
    def search(request: Request, who: Who, svc: Services, q: str = "") -> HTMLResponse:
        query = q.strip()
        results = svc.views.search(query, SEARCH_LIMIT) if query else []
        return render(request, who, "search.html", query=query, results=results, limit=SEARCH_LIMIT)

    @app.get("/documents/new", response_class=HTMLResponse)
    def new_document(request: Request, who: Who) -> HTMLResponse:
        return render(request, who, "add_document.html", values={"language": "id", "rights": "public"}, problems={})

    @app.get("/documents/{document_id}", response_class=HTMLResponse)
    def document(request: Request, who: Who, svc: Services, document_id: str) -> HTMLResponse:
        return document_page(request, who, svc, document_id)

    @app.get("/documents/{document_id}/content/{sha256}")
    def content(who: Who, svc: Services, document_id: str, sha256: str) -> Response:
        stored = svc.views.stored(document_id, sha256)
        if stored is None:
            raise HTTPException(404, f"{document_id} has no file or text {sha256[:12]}")
        disposition = f"inline; filename*=UTF-8''{quote(stored.name)}"
        return Response(
            svc.blobs.read(stored.storage_key),
            media_type=stored.media_type,
            headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
        )

    # --- changes -------------------------------------------------------------------------------

    def act(
        request: Request,
        who: Curator,
        svc: WebServices,
        document_id: str,
        change: Callable[[], None],
        done: str,
        anchor: str,
        form: str,
    ) -> Response:
        """Run a change on a document; on a bad value or a refusal, show the page again with why."""
        try:
            change()
        except InvalidCorrection as error:
            return document_page(request, who, svc, document_id, 422, errors={form: str(error)})
        except CurationRefused as error:
            return document_page(request, who, svc, document_id, 409, errors={form: str(error)})
        return after_change(svc, f"/documents/{quote(document_id)}#{anchor}", done)

    @app.post("/documents/{document_id}/corrections")
    def correct(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        field: Annotated[str, Form()],
        value: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.correct, who, document_id, field, value, reason)
        return act(request, who, svc, document_id, change, "corrected", "fields", "correction")

    @app.post("/documents/{document_id}/texts/{text_sha256}/approve")
    def approve(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        text_sha256: str,
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.approve, who, document_id, text_sha256, reason)
        return act(request, who, svc, document_id, change, "approved", "content", f"approve-{text_sha256}")

    @app.post("/documents/{document_id}/texts/{text_sha256}/approve/withdraw")
    def withdraw_approval(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        text_sha256: str,
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.withdraw_approval, who, document_id, text_sha256, reason)
        return act(request, who, svc, document_id, change, "unapproved", "content", f"approve-{text_sha256}")

    @app.get("/documents/{document_id}/texts/{text_sha256}/edit", response_class=HTMLResponse)
    def edit_text(request: Request, who: Who, svc: Services, document_id: str, text_sha256: str) -> HTMLResponse:
        text = svc.views.editable_text(document_id, text_sha256)
        if text is None:
            missing = f"{document_id} has no current main text {text_sha256[:12]}"
            return render(request, who, "missing.html", 404, what=missing)
        wording = svc.blobs.read(text.storage_key).decode("utf-8")
        return render(request, who, "edit_text.html", text=text, wording=wording, reason="", error=None)

    @app.post("/documents/{document_id}/texts/{text_sha256}/correction")
    def correct_text(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        text_sha256: str,
        wording: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        try:
            svc.correct_text.correct(who, document_id, text_sha256, wording, reason)
        except (InvalidCorrection, CurationRefused) as error:
            text = svc.views.editable_text(document_id, text_sha256)
            if text is None:
                return render(request, who, "missing.html", 404, what=str(error))
            status = 422 if isinstance(error, InvalidCorrection) else 409
            context = {"text": text, "wording": wording, "reason": reason, "error": str(error)}
            return render(request, who, "edit_text.html", status, **context)
        return after_change(svc, f"/documents/{quote(document_id)}#content", "text_corrected")

    @app.post("/documents/{document_id}/texts/{text_sha256}/correction/withdraw")
    def withdraw_text_correction(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        text_sha256: str,
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.correct_text.withdraw, who, document_id, text_sha256, reason)
        return act(request, who, svc, document_id, change, "text_restored", "content", f"correction-{text_sha256}")

    @app.get("/documents/{document_id}/texts/{text_sha256}/correction", response_class=HTMLResponse)
    def correction(request: Request, who: Who, svc: Services, document_id: str, text_sha256: str) -> HTMLResponse:
        found = svc.views.correction(document_id, text_sha256)
        if found is None:
            missing = f"{text_sha256[:12]} of {document_id} has no correction"
            return render(request, who, "missing.html", 404, what=missing)
        before = svc.blobs.read(found.source_storage_key).decode("utf-8")
        after = svc.blobs.read(found.corrected_storage_key).decode("utf-8")
        return render(request, who, "correction.html", correction=found, diff=presentation.text_diff(before, after))

    @app.post("/documents/{document_id}/corrections/withdraw")
    def withdraw(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        field: Annotated[str, Form()],
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.withdraw_correction, who, document_id, field, reason)
        return act(request, who, svc, document_id, change, "withdrawn", "fields", f"withdraw-{field}")

    @app.post("/documents/{document_id}/suppress")
    def suppress(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        reason: Annotated[str, Form()] = "",
        confirm: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)

        def change() -> None:
            if confirm != "yes":
                raise InvalidCorrection("tick the box to confirm: the document leaves what the assistant can cite")
            svc.curate.suppress(who, document_id, reason)

        return act(request, who, svc, document_id, change, "suppressed", "manage", "suppress")

    @app.post("/documents/{document_id}/restore")
    def restore(
        request: Request, who: Who, svc: Services, token: Token, document_id: str, reason: Annotated[str, Form()] = ""
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.restore, who, document_id, reason)
        return act(request, who, svc, document_id, change, "restored", "manage", "restore")

    @app.post("/documents/{document_id}/assign-id")
    def assign_id(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        new_id: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        try:
            svc.curate.assign_id(who, document_id, new_id, reason)
        except (InvalidCorrection, CurationRefused) as error:
            status = 422 if isinstance(error, InvalidCorrection) else 409
            return document_page(request, who, svc, document_id, status, errors={"assign": str(error)})
        return after_change(svc, f"/documents/{quote(new_id.strip().lower())}", "renamed")

    @app.post("/documents/{document_id}/citations/{citation_id}/link")
    def link_citation(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        citation_id: int,
        target_id: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.link_citation, who, citation_id, target_id, reason)
        return act(request, who, svc, document_id, change, "linked", "citations", f"citation-{citation_id}")

    @app.post("/documents/{document_id}/conflicts/{conflict_id}")
    def resolve_conflict(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        document_id: str,
        conflict_id: int,
        decision: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
    ) -> Response:
        who = checked(request, who, token)
        change = partial(svc.curate.resolve_conflict, who, conflict_id, decision, note)
        return act(request, who, svc, document_id, change, "conflict", "conflicts", f"conflict-{conflict_id}")

    @app.post("/review/{item_id}")
    def decide_review(
        request: Request,
        who: Who,
        svc: Services,
        token: Token,
        item_id: int,
        state: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        back: Annotated[str, Form()] = "/review",
    ) -> Response:
        who = checked(request, who, token)
        back = back if back.startswith("/") and not back.startswith("//") else "/review"  # never redirect off-site
        try:
            svc.curate.decide_review(who, item_id, state, note)
        except (InvalidCorrection, CurationRefused) as error:
            target = urlsplit(back)
            return RedirectResponse(
                f"{target.path}?{urlencode({**_query(target.query), 'error': str(error)})}", status_code=303
            )
        return after_change(svc, back, state)

    @app.post("/documents/new")
    async def add_document(
        request: Request, who: Who, svc: Services, token: Token, file: UploadFile | None = None
    ) -> Response:
        who = checked(request, who, token)
        form = await request.form()
        values = {name: str(form.get(name, "")) for name in presentation.MANUAL_FIELDS}
        data = await file.read(MAX_UPLOAD_BYTES + 1) if file and file.filename else b""
        if len(data) > MAX_UPLOAD_BYTES:
            return render(
                request,
                who,
                "add_document.html",
                413,
                values=values,
                problems={"file": "the file is over 100 MB; ask an engineer to load it"},
            )
        entry = ManualDocument(
            **values,
            file_name=file.filename if file else "",
            file_bytes=data,
            media_type=(file.content_type if file else "") or "application/octet-stream",
        )
        try:
            document_id = svc.add_manual.run(who, entry)
        except InvalidManualDocument as error:
            return render(request, who, "add_document.html", 422, values=values, problems=error.problems)
        except CurationRefused as error:
            return render(request, who, "add_document.html", 409, values=values, problems={"document_id": str(error)})
        return after_change(svc, f"/documents/{quote(document_id)}", "added")

    @app.exception_handler(HTTPException)
    def http_error(request: Request, error: HTTPException) -> Response:
        if error.status_code == 401:
            return PlainTextResponse(str(error.detail), 401, headers=error.headers)
        return templates.TemplateResponse(
            request,
            "missing.html",
            {"what": error.detail, "curator": None, "done": None},
            status_code=error.status_code,
        )

    return app


def _query(raw: str) -> dict[str, str]:
    return {key: value for key, value in parse_qsl(raw) if key not in ("error", "done")}
