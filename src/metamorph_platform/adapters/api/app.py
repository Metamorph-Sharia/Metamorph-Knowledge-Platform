"""The curation JSON API (/api/v1): the curation use cases and read models over HTTP.

Its one client is the curation web app's server (Metamorph-Curation-Web), on the private network: browsers
never call it. A curator signs in once for a short-lived token (tokens.py) and sends it as a bearer token,
so every action is audited under the right name. The contract is the OpenAPI document this app generates,
committed as docs/api/openapi.json.

Every action runs its use case, then parses what changed and publishes, and only then answers: the
answer says whether the document now passes the publish gate. Errors keep the use cases' meaning:
    422 {"error": "invalid", "message", "fields"}   what the curator entered can't be applied
    409 {"error": "refused", "message"}             the action can't apply as asked
    401 {"error": "unauthorized", "message"}        no token, a forged one, or an expired one
    404 {"error": "not_found", "message"}
"""

# No `from __future__ import annotations`: FastAPI reads the dependency annotations at runtime.
import difflib
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Protocol, TypeVar

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from metamorph_platform.adapters.api.accounts import Accounts
from metamorph_platform.adapters.api.tokens import TOKEN_LIFETIME, InvalidToken, issue, verify
from metamorph_platform.application.add_manual_document import AddManualDocument
from metamorph_platform.application.curate import CorrectText, Curate
from metamorph_platform.application.curate_market import CurateMarket
from metamorph_platform.application.market_views import (
    BUSINESS_TYPES,
    COMPANY_STATUSES,
    CompanyFilters,
    CompanyPage,
    CompanyView,
    DatasetFilters,
    DatasetPage,
    DatasetView,
    IndustryName,
    MarketOverview,
    MarketSources,
    MarketViews,
    ReleasePage,
    ReleaseView,
    ReportRow,
    ReportView,
    SeriesView,
)
from metamorph_platform.application.parse_texts import ParseTexts
from metamorph_platform.application.ports import BlobReader, CurationRefused, Curator
from metamorph_platform.application.publish import Publish
from metamorph_platform.application.reading import ReadText
from metamorph_platform.application.views import (
    HELD_CHECKS,
    REVIEW_KINDS,
    SEARCH_KINDS,
    STATES,
    CorrectionView,
    CurationViews,
    Dashboard,
    DocumentView,
    EditableText,
    GapPage,
    HeldPage,
    ReviewPage,
    SearchFilters,
    SearchPage,
    SeriesPage,
    SeriesRow,
    TextReading,
)
from metamorph_platform.domain.curation import InvalidCorrection, validate_assigned_id
from metamorph_platform.domain.manual import InvalidManualDocument, ManualDocument

API = "/api/v1"
T = TypeVar("T")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # UU 4/2023, the largest file we hold, is 82 MB
UPLOADS = "uploads/"  # where browsers put files: a document is only ever added from one of these


class FileLinks(Protocol):
    """Short-lived links straight to the object store, so files never pass through this API (or the web app)."""

    def download_url(self, storage_key: str, *, name: str, media_type: str) -> str: ...

    def upload_url(self, key: str, *, media_type: str) -> str: ...

    def uploaded(self, key: str) -> bytes | None:
        """What the browser uploaded under `key`; None if nothing was."""


@dataclass
class ApiServices:
    views: CurationViews
    curate: Curate
    correct_text: CorrectText
    add_manual: AddManualDocument
    parse: ParseTexts  # only what changed: a corrected text
    publish: Publish
    blobs: BlobReader
    files: FileLinks
    market_views: MarketViews
    curate_market: CurateMarket


ServicesFactory = Callable[[], AbstractContextManager[ApiServices]]
Clock = Callable[[], datetime]


class SignIn(BaseModel):
    username: str
    password: str


class Session(BaseModel):
    token: str
    curator: Curator
    expires_at: datetime


class TextToEdit(BaseModel):
    text: EditableText
    wording: str  # its effective wording now: the source's, or a curator's correction


class CorrectionDiff(BaseModel):
    correction: CorrectionView
    source: str
    corrected: str
    diff: list[str]  # unified, source → correction


class Link(BaseModel):
    url: str


class Reason(BaseModel):
    reason: str = ""  # every action needs one: the next reviewer reads it in the audit log


class FieldCorrection(Reason):
    field: str
    value: str = ""


class Wording(Reason):
    wording: str


class Suppression(Reason):
    confirm: bool = False  # suppressing removes the document from what the assistant reads: say so explicitly


class NewId(Reason):
    new_id: str


class CitationTarget(Reason):
    target_id: str


class ConflictDecision(Reason):
    decision: str  # keep | accept


class ReviewDecision(Reason):
    state: str  # resolved | dismissed


class Done(BaseModel):
    done: str


class Upload(BaseModel):
    file_name: str
    media_type: str = "application/octet-stream"


class UploadLink(BaseModel):
    upload_key: str
    url: str  # PUT the file here, with the same media type, before adding the document


class NewDocument(Reason):
    """A document no connector holds (domain/manual.py), its file uploaded first (POST /uploads)."""

    document_id: str
    citation: str
    title: str
    kind: str
    status: str
    language: str = "id"
    source_url: str
    rights: str = "public"
    text: str = ""
    enacted_on: str = ""
    promulgated_on: str = ""
    effective_on: str = ""
    file_name: str
    media_type: str = "application/octet-stream"
    upload_key: str


class RegisterLinksChange(Reason):
    governed_by: list[str] = []  # document IDs, e.g. ojk:pojk:2024:40
    reports: list[str] = []  # report IDs or families, e.g. ojk:lpksi
    fresh_days: int


class IndustryChange(Reason):
    # the industry takes the register's regulations, or its own: not both. `register` in JSON; the field is named
    # otherwise, since pydantic models have a `register` of their own
    register_id: str | None = Field(default=None, alias="register")
    governed_by: list[str] = []
    reports: list[str] = []


class SourceChange(Reason):
    citation: str = ""
    fresh_days: int
    download_page: str = ""  # where a curator downloads an edition by hand
    download_hint: str = ""


class SectorChange(Reason):
    name: str
    name_en: str = ""
    industries: list[IndustryName]  # in the curator's order


class MarketChange(BaseModel):
    """A change to the curated links, as published: what it named that is not published, and the sources page."""

    warnings: list[str]
    sources: MarketSources


class Unauthorized(Exception):
    pass


class NotFound(Exception):
    pass


def create_api(
    open_services: ServicesFactory, accounts: Accounts, secret: str, *, clock: Clock = lambda: datetime.now(UTC)
) -> FastAPI:
    app = FastAPI(
        title="Metamorph Curation API", version="1", docs_url=None, redoc_url=None, openapi_url=f"{API}/openapi.json"
    )
    bearer = HTTPBearer(auto_error=False)

    def curator(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Curator:
        if credentials is None:
            raise Unauthorized("sign in first: send the session token as a bearer token")
        try:
            return verify(credentials.credentials, secret, now=clock())
        except (InvalidToken, ValueError, KeyError) as error:
            raise Unauthorized(str(error)) from error

    def services() -> Iterator[ApiServices]:
        with open_services() as opened:
            yield opened

    Who = Annotated[Curator, Depends(curator)]
    Services = Annotated[ApiServices, Depends(services)]

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.post(f"{API}/auth/session", tags=["auth"])
    def sign_in(credentials: SignIn) -> Session:
        signed_in = accounts.verify(credentials.username, credentials.password)
        if signed_in is None:
            raise Unauthorized("the username or password is wrong")
        now = clock()
        return Session(token=issue(signed_in, secret, now=now), curator=signed_in, expires_at=now + TOKEN_LIFETIME)

    router = APIRouter(prefix=API)

    @router.get("/auth/session", tags=["auth"])
    def session(who: Who) -> Curator:
        return who

    @router.get("/overview", tags=["reads"])
    def overview(who: Who, svc: Services) -> Dashboard:
        return svc.views.dashboard()

    @router.get("/held", tags=["reads"])
    def held(who: Who, svc: Services, check: str = "", page: int = 1) -> HeldPage:
        if check and check not in HELD_CHECKS:
            raise NotFound(f"no check {check}")
        return svc.views.held_page(check or None, page)

    @router.get("/gaps", tags=["reads"])
    def gaps(who: Who, svc: Services, page: int = 1) -> GapPage:
        return svc.views.gap_page(page)

    @router.get("/reviews", tags=["reads"])
    def reviews(who: Who, svc: Services, kind: str = REVIEW_KINDS[0], page: int = 1) -> ReviewPage:
        if kind not in REVIEW_KINDS:
            raise NotFound(f"no review queue {kind}")
        return svc.views.review_page(kind, page)

    @router.get("/documents", tags=["reads"])
    def search(
        who: Who,
        svc: Services,
        q: str = "",
        kind: str = SEARCH_KINDS[0],
        issuer: str = "",
        family: str = "",
        year: int | None = None,
        status: str = "",
        state: str = "",
        page: int = 1,
    ) -> SearchPage:
        """Documents whose metadata or published wording matches `q` (all of them when it is empty), or, with
        kind=articles, the matching articles; filtered, with each filter's counts."""
        if kind not in SEARCH_KINDS:
            raise NotFound(f"no search of {kind}")
        if state and state not in STATES:
            raise NotFound(f"no state {state}")
        filters = SearchFilters(issuer or None, family or None, year, status or None, state or None)
        return svc.views.search(q.strip(), filters, kind, max(page, 1))

    @router.get("/series", tags=["reads"])
    def series(who: Who, svc: Services) -> list[SeriesRow]:
        """Each issuer's families of instruments, with what the registry holds of them."""
        return list(svc.views.series())

    @router.get("/series/{issuer}/{family}", tags=["reads"])
    def series_page(who: Who, svc: Services, issuer: str, family: str, year: int | None = None) -> SeriesPage:
        """A family's documents of one year (the newest when none is asked for), by number."""
        return _found(svc.views.series_page(issuer, family, year), f"no series {issuer}:{family}")

    @router.get("/documents/{document_id}", tags=["reads"])
    def document(who: Who, svc: Services, document_id: str) -> DocumentView:
        return _found(svc.views.document(document_id), f"no document {document_id}")

    @router.get("/documents/{document_id}/reading", tags=["reads"])
    def reading(who: Who, svc: Services, document_id: str, text: str = "", part: int = 0, at: str = "") -> TextReading:
        """A text as the parser cut it, one part at a time: `text` (the main text when empty), and the part asked
        for or the one the provision `at` opens in."""
        found = ReadText(svc.views, svc.blobs).read(document_id, text or None, part=part, at=at or None)
        return _found(found, f"no text to read for {document_id}")

    @router.get("/documents/{document_id}/texts/{text_sha256}/editable", tags=["reads"])
    def editable(who: Who, svc: Services, document_id: str, text_sha256: str) -> TextToEdit:
        text = _found(
            svc.views.editable_text(document_id, text_sha256),
            f"{document_id} has no current main text {text_sha256[:12]}",
        )
        return TextToEdit(text=text, wording=svc.blobs.read(text.storage_key).decode("utf-8"))

    @router.get("/documents/{document_id}/texts/{text_sha256}/correction", tags=["reads"])
    def correction(who: Who, svc: Services, document_id: str, text_sha256: str) -> CorrectionDiff:
        found = _found(
            svc.views.correction(document_id, text_sha256), f"{text_sha256[:12]} of {document_id} has no correction"
        )
        source = svc.blobs.read(found.source_storage_key).decode("utf-8")
        corrected = svc.blobs.read(found.corrected_storage_key).decode("utf-8")
        return CorrectionDiff(correction=found, source=source, corrected=corrected, diff=_diff(source, corrected))

    @router.get("/documents/{document_id}/content/{sha256}", tags=["reads"])
    def content(who: Who, svc: Services, document_id: str, sha256: str) -> Link:
        stored = _found(svc.views.stored(document_id, sha256), f"{document_id} has no file or text {sha256[:12]}")
        return Link(url=svc.files.download_url(stored.storage_key, name=stored.name, media_type=stored.media_type))

    # --- actions: the use case, then parse and publish what changed, then the document as it is now ----------

    def changed(svc: ApiServices, document_id: str) -> DocumentView:
        svc.parse.run()
        svc.publish.run()
        return _found(svc.views.document(document_id), f"no document {document_id}")

    @router.post("/documents/{document_id}/corrections", tags=["actions"])
    def correct(who: Who, svc: Services, document_id: str, body: FieldCorrection) -> DocumentView:
        svc.curate.correct(who, document_id, body.field, body.value, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/corrections/{field}/withdraw", tags=["actions"])
    def withdraw_correction(who: Who, svc: Services, document_id: str, field: str, body: Reason) -> DocumentView:
        svc.curate.withdraw_correction(who, document_id, field, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/texts/{text_sha256}/approval", tags=["actions"])
    def approve(who: Who, svc: Services, document_id: str, text_sha256: str, body: Reason) -> DocumentView:
        svc.curate.approve(who, document_id, text_sha256, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/texts/{text_sha256}/approval/withdraw", tags=["actions"])
    def withdraw_approval(who: Who, svc: Services, document_id: str, text_sha256: str, body: Reason) -> DocumentView:
        svc.curate.withdraw_approval(who, document_id, text_sha256, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/texts/{text_sha256}/correction", tags=["actions"])
    def correct_text(who: Who, svc: Services, document_id: str, text_sha256: str, body: Wording) -> DocumentView:
        svc.correct_text.correct(who, document_id, text_sha256, body.wording, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/texts/{text_sha256}/correction/withdraw", tags=["actions"])
    def withdraw_text_correction(
        who: Who, svc: Services, document_id: str, text_sha256: str, body: Reason
    ) -> DocumentView:
        svc.correct_text.withdraw(who, document_id, text_sha256, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/suppression", tags=["actions"])
    def suppress(who: Who, svc: Services, document_id: str, body: Suppression) -> DocumentView:
        if not body.confirm:
            raise InvalidCorrection("confirm the suppression: it removes the document from what the assistant reads")
        svc.curate.suppress(who, document_id, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/restore", tags=["actions"])
    def restore(who: Who, svc: Services, document_id: str, body: Reason) -> DocumentView:
        svc.curate.restore(who, document_id, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/id", tags=["actions"])
    def assign_id(who: Who, svc: Services, document_id: str, body: NewId) -> DocumentView:
        """Answers the document under its new ID."""
        svc.curate.assign_id(who, document_id, body.new_id, body.reason)
        return changed(svc, validate_assigned_id(body.new_id))

    @router.post("/documents/{document_id}/citations/{citation_id}/link", tags=["actions"])
    def link_citation(
        who: Who, svc: Services, document_id: str, citation_id: int, body: CitationTarget
    ) -> DocumentView:
        svc.curate.link_citation(who, citation_id, body.target_id, body.reason)
        return changed(svc, document_id)

    @router.post("/documents/{document_id}/conflicts/{conflict_id}", tags=["actions"])
    def resolve_conflict(
        who: Who, svc: Services, document_id: str, conflict_id: int, body: ConflictDecision
    ) -> DocumentView:
        svc.curate.resolve_conflict(who, conflict_id, body.decision, body.reason)
        return changed(svc, document_id)

    @router.post("/uploads", tags=["actions"])
    def upload(who: Who, svc: Services, body: Upload) -> UploadLink:
        key = f"{UPLOADS}{uuid.uuid4().hex}"
        return UploadLink(upload_key=key, url=svc.files.upload_url(key, media_type=body.media_type))

    @router.post("/documents", tags=["actions"])
    def add_document(who: Who, svc: Services, body: NewDocument) -> DocumentView:
        data = (svc.files.uploaded(body.upload_key) if body.upload_key.startswith(UPLOADS) else None) or b""
        if len(data) > MAX_UPLOAD_BYTES:
            raise InvalidManualDocument({"file": "the file is over 100 MB; ask an engineer to load it"})
        fields = body.model_dump(exclude={"upload_key"})
        document_id = svc.add_manual.run(who, ManualDocument(**fields, file_bytes=data))
        return changed(svc, document_id)

    @router.post("/reviews/{item_id}", tags=["actions"])
    def decide_review(who: Who, svc: Services, item_id: int, body: ReviewDecision) -> Done:
        svc.curate.decide_review(who, item_id, body.state, body.reason)
        svc.parse.run()
        svc.publish.run()
        return Done(done=body.state)

    # --- the market layer: its pages' reads, and changes to its curated links ---------------------------------

    @router.get("/market/overview", tags=["market"])
    def market_overview(who: Who, svc: Services) -> MarketOverview:
        return svc.market_views.overview()

    @router.get("/market/sources", tags=["market"])
    def market_sources(who: Who, svc: Services) -> MarketSources:
        """Registers and statistics sources with their curated links, the industries and the sectors."""
        return svc.market_views.sources()

    @router.get("/market/companies", tags=["market"])
    def companies(
        who: Who, svc: Services, q: str = "", register: str = "", status: str = "", business_type: str = "",
        page: int = 1,
    ) -> CompanyPage:
        _chosen(status, COMPANY_STATUSES, "company status")
        _chosen(business_type, BUSINESS_TYPES, "business type")
        filters = CompanyFilters(register or None, status or None, business_type or None)
        return svc.market_views.companies(q.strip(), filters, max(page, 1))

    @router.get("/market/companies/{company_id}", tags=["market"])
    def company(who: Who, svc: Services, company_id: str) -> CompanyView:
        return _found(svc.market_views.company(company_id), f"no company {company_id}")

    @router.get("/market/datasets", tags=["market"])
    def datasets(
        who: Who, svc: Services, q: str = "", source: str = "", industry: str = "", page: int = 1
    ) -> DatasetPage:
        return svc.market_views.datasets(q.strip(), DatasetFilters(source or None, industry or None), max(page, 1))

    @router.get("/market/datasets/{dataset_id}", tags=["market"])
    def dataset(who: Who, svc: Services, dataset_id: str, page: int = 1) -> DatasetView:
        """A dataset with a page of its series."""
        return _found(svc.market_views.dataset(dataset_id, max(page, 1)), f"no dataset {dataset_id}")

    @router.get("/market/series/{series_id}", tags=["market"])
    def market_series(who: Who, svc: Services, series_id: str) -> SeriesView:
        """A series with every observation, oldest first."""
        return _found(svc.market_views.series(series_id), f"no series {series_id}")

    @router.get("/market/reports", tags=["market"])
    def reports(who: Who, svc: Services) -> list[ReportRow]:
        return list(svc.market_views.reports())

    @router.get("/market/reports/{report_id}", tags=["market"])
    def report(who: Who, svc: Services, report_id: str, page: int = 1) -> ReportView:
        """A report with a page of its passages, each with what it names."""
        return _found(svc.market_views.report(report_id, max(page, 1)), f"no report {report_id}")

    @router.get("/market/releases", tags=["market"])
    def releases(
        who: Who, svc: Services, q: str = "", published_from: Annotated[date | None, Query(alias="from")] = None,
        published_to: Annotated[date | None, Query(alias="to")] = None, page: int = 1,
    ) -> ReleasePage:
        """Press releases, newest first; `from` and `to` bound their published date."""
        return svc.market_views.releases(q.strip(), published_from, published_to, max(page, 1))

    @router.get("/market/releases/{release_id}", tags=["market"])
    def release(who: Who, svc: Services, release_id: str) -> ReleaseView:
        return _found(svc.market_views.release(release_id), f"no release {release_id}")

    def market_changed(svc: ApiServices, warnings: tuple[str, ...]) -> MarketChange:
        return MarketChange(warnings=list(warnings), sources=svc.market_views.sources())

    @router.put("/market/registers/{register_id}/links", tags=["market"])
    def set_register_links(who: Who, svc: Services, register_id: str, body: RegisterLinksChange) -> MarketChange:
        """Replace a register's curated links; published at once."""
        warnings = svc.curate_market.set_register_links(who, register_id, body.governed_by, body.reports,
                                                        body.fresh_days, body.reason)
        return market_changed(svc, warnings)

    @router.put("/market/sources/{source_id}", tags=["market"])
    def set_source(who: Who, svc: Services, source_id: str, body: SourceChange) -> MarketChange:
        warnings = svc.curate_market.set_source(who, source_id, body.citation, body.fresh_days, body.download_page,
                                                body.download_hint, body.reason)
        return market_changed(svc, warnings)

    @router.put("/market/sources/{source_id}/industries/{name}", tags=["market"])
    def set_industry(who: Who, svc: Services, source_id: str, name: str, body: IndustryChange) -> MarketChange:
        """Add an industry as its source names it, or replace its links; published at once."""
        warnings = svc.curate_market.set_industry(who, source_id, name, body.register_id, body.governed_by,
                                                  body.reports, body.reason)
        return market_changed(svc, warnings)

    @router.post("/market/sources/{source_id}/industries/{name}/withdraw", tags=["market"])
    def withdraw_industry(who: Who, svc: Services, source_id: str, name: str, body: Reason) -> MarketChange:
        return market_changed(svc, svc.curate_market.withdraw_industry(who, source_id, name, body.reason))

    @router.put("/market/sectors/{sector_id}", tags=["market"])
    def set_sector(who: Who, svc: Services, sector_id: str, body: SectorChange) -> MarketChange:
        """Add a sector, or replace its names and industries; published at once."""
        industries = [(industry.source, industry.name) for industry in body.industries]
        return market_changed(
            svc, svc.curate_market.set_sector(who, sector_id, body.name, body.name_en, industries, body.reason)
        )

    @router.post("/market/sectors/{sector_id}/withdraw", tags=["market"])
    def withdraw_sector(who: Who, svc: Services, sector_id: str, body: Reason) -> MarketChange:
        return market_changed(svc, svc.curate_market.withdraw_sector(who, sector_id, body.reason))

    app.include_router(router)

    @app.exception_handler(Unauthorized)
    def unauthorized(request: Request, error: Unauthorized) -> JSONResponse:
        return _error(401, "unauthorized", str(error), headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(InvalidManualDocument)
    def invalid_document(request: Request, error: InvalidManualDocument) -> JSONResponse:
        return _error(422, "invalid", str(error), fields=error.problems)

    @app.exception_handler(InvalidCorrection)
    def invalid(request: Request, error: InvalidCorrection) -> JSONResponse:
        return _error(422, "invalid", str(error), fields={})

    @app.exception_handler(CurationRefused)
    def refused(request: Request, error: CurationRefused) -> JSONResponse:
        return _error(409, "refused", str(error))

    @app.exception_handler(NotFound)
    def not_found(request: Request, error: NotFound) -> JSONResponse:
        return _error(404, "not_found", str(error))

    return app


def _found(value: T | None, missing: str) -> T:
    if value is None:
        raise NotFound(missing)
    return value


def _chosen(value: str, choices: tuple[str, ...], what: str) -> None:
    if value and value not in choices:
        raise NotFound(f"no {what} {value}: {', '.join(choices[:-1])} or {choices[-1]}")


def _diff(source: str, corrected: str) -> list[str]:
    return list(difflib.unified_diff(source.splitlines(), corrected.splitlines(), "source", "correction", lineterm=""))


def _error(status: int, kind: str, message: str, **extra) -> JSONResponse:
    headers = extra.pop("headers", None)
    return JSONResponse({"error": kind, "message": message, **extra}, status_code=status, headers=headers)
