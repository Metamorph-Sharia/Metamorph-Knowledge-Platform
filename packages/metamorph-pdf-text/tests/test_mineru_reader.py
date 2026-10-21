"""The MinerU reader against a scripted V1 service: the responses carry the fields of MinerU 4.0.12's models
(mineru/parser/api_server.py: UploadResponse, JobAsyncResponse, JobFileResult, OutputFiles, ErrorResponse)."""

from __future__ import annotations

import json

import httpx
import pytest
from metamorph_pdf_text import ExtractionFailed, ExtractionUnavailable, OcrMode, ReadRequest, Tier
from metamorph_pdf_text.adapters.mineru_reader import MINERU_VERSION, WAIT_SECONDS, MinerUReader
from pdf_text_files import middle_json

URL = "http://mineru.test:8010"
PDF = b"%PDF-1.7 Perpres 10/2021"
REQUEST = ReadRequest(Tier.STANDARD, OcrMode.AUTO)


class FakeMinerU:
    """A V1 service: answers each request in turn, and keeps what it was sent."""

    def __init__(self, *, version: str = MINERU_VERSION, holds_file: bool = False, statuses=("running", "completed")):
        self.version, self.holds_file, self.statuses = version, holds_file, list(statuses)
        self.tiers = ["flash", "basic", "standard", "advanced"]  # what `--tier standard` serves
        self.file_status, self.answers = "completed", {}  # (method, path) → a response, instead of the script
        self.sent: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        route = (request.method, request.url.path)
        if route in self.answers:
            return self.answers[route]
        match route:
            case ("GET", "/v1/health"):
                return httpx.Response(200, json={"version": self.version, "features": {"sources": ["file_id"]}})
            case ("GET", "/v1/tiers"):
                tiers = [{"id": tier, "description": tier, "current_model": "mineru-4.0.12"} for tier in self.tiers]
                return httpx.Response(200, json={"object": "list", "data": tiers})
            case ("POST", "/v1/uploads"):
                return httpx.Response(200, json=self._upload("completed" if self.holds_file else "pending"))
            case ("PUT", "/v1/uploads/upload_1/content"):
                return httpx.Response(200)
            case ("POST", "/v1/uploads/upload_1/complete"):
                return httpx.Response(200, json=self._upload("completed"))
            case ("POST", "/v1/parse/jobs"):
                return httpx.Response(202, json=self._job("queued"))
            case ("GET", "/v1/parse/jobs/job_1"):
                return httpx.Response(200, json=self._job(self.statuses.pop(0)))
            case ("GET", "/v1/files/file-middle/content"):
                return httpx.Response(200, content=json.dumps(middle_json()).encode())
        return httpx.Response(404, json={"error": {"type": "invalid_request_error", "message": "no such route"}})

    def paths(self) -> list[str]:
        return [f"{request.method} {request.url.path}" for request in self.sent]

    def body(self, path: str) -> dict:
        return json.loads(next(request for request in self.sent if request.url.path == path).content)

    def _upload(self, status: str) -> dict:
        upload = {"id": "upload_1", "object": "upload", "bytes": len(PDF), "created_at": 1, "expires_at": 2}
        upload |= {"filename": "x.pdf", "purpose": "parse", "mime_type": "application/pdf", "status": status}
        if status == "pending":
            upload |= {"upload_url": f"{URL}/v1/uploads/upload_1/content", "upload_method": "PUT"}
            upload["upload_headers"] = {"Content-Type": "application/octet-stream"}
        else:
            upload["file"] = {"id": "file-source", "object": "file", "bytes": len(PDF), "created_at": 1}
            upload["file"] |= {"filename": "x.pdf", "purpose": "parse"}
        return upload

    def _job(self, status: str) -> dict:
        result = {"file_id": "file-source", "name": "x.pdf", "page_range": "all", "status": "running"}
        if status in ("completed", "partial", "failed"):
            result["status"] = self.file_status
            if self.file_status == "completed":
                result["output_files"] = {"middle_json": {"file_id": "file-middle", "bytes": 4096}}
            else:
                result["error"] = {"type": "engine_error", "code": "parse_failed", "message": "PDF is encrypted"}
        return {
            "job_id": "job_1",
            "status": status,
            "created_at": "2026-10-20T00:00:00Z",
            "tier": "standard",
            "output_formats": ["middle_json"],
            "access_level": "api_key",
            "files": [result],
            "links": {"self": "/v1/parse/jobs/job_1", "cancel": "/v1/parse/jobs/job_1"},
        }


def reader(service: FakeMinerU, *, api_key: str | None = None, sleeps: list | None = None, clock=None) -> MinerUReader:
    return MinerUReader(
        URL,
        api_key,
        transport=httpx.MockTransport(service),
        sleep=(sleeps if sleeps is not None else []).append,
        clock=clock or (lambda: 0.0),
    )


def test_a_pdf_is_uploaded_parsed_and_its_middle_json_read() -> None:
    service = FakeMinerU()

    reading = reader(service).read(PDF, REQUEST)

    assert [page.number for page in reading.pages] == [1, 2]
    assert service.paths() == [
        "GET /v1/health",
        "POST /v1/uploads",
        "PUT /v1/uploads/upload_1/content",
        "POST /v1/uploads/upload_1/complete",
        "POST /v1/parse/jobs",
        "GET /v1/parse/jobs/job_1",
        "GET /v1/parse/jobs/job_1",
        "GET /v1/files/file-middle/content",
    ]


def test_the_requests_carry_only_the_fields_the_service_accepts() -> None:
    service = FakeMinerU()

    reader(service).read(PDF, ReadRequest(Tier.BASIC, OcrMode.OCR))

    upload = service.body("/v1/uploads")
    assert set(upload) == {"filename", "bytes", "mime_type", "sha256sum"}
    assert upload["bytes"] == len(PDF) and len(upload["sha256sum"]) == 64
    assert service.body("/v1/parse/jobs") == {
        "files": [{"source": {"type": "file_id", "file_id": "file-source"}}],
        "tier": "basic",
        "ocr_mode": "ocr",
        "output_formats": ["middle_json"],
    }


def test_a_file_the_service_holds_is_not_uploaded_again() -> None:
    service = FakeMinerU(holds_file=True)

    reader(service).read(PDF, REQUEST)

    assert "PUT /v1/uploads/upload_1/content" not in service.paths()


def test_the_api_key_is_sent_as_a_bearer_token() -> None:
    service = FakeMinerU()

    reader(service, api_key="secret").read(PDF, REQUEST)

    assert {request.headers.get("Authorization") for request in service.sent} == {"Bearer secret"}


def test_a_job_is_polled_until_it_is_done() -> None:
    service, sleeps = FakeMinerU(statuses=("queued", "running", "running", "completed")), []

    reader(service, sleeps=sleeps).read(PDF, REQUEST)

    assert len(sleeps) == 3


def test_the_version_is_minerus_and_the_translations() -> None:
    assert reader(FakeMinerU()).version == f"{MINERU_VERSION}+t1"


def test_another_minerus_version_is_refused_before_it_is_sent_the_file() -> None:
    service = FakeMinerU(version="4.0.13")

    with pytest.raises(ExtractionFailed, match="4.0.13"):
        reader(service).read(PDF, REQUEST)
    assert service.paths() == ["GET /v1/health"]


def test_the_tiers_served_are_those_this_reader_asks_for() -> None:
    service = FakeMinerU()
    service.tiers = ["flash", "basic"]  # a service started with --tier basic

    assert reader(service).tiers() == {Tier.BASIC}


def test_a_file_the_service_could_not_parse_fails() -> None:
    service = FakeMinerU(statuses=("failed",))
    service.file_status = "failed"

    with pytest.raises(ExtractionFailed, match="PDF is encrypted"):
        reader(service).read(PDF, REQUEST)


@pytest.mark.parametrize(
    ("route", "status"),
    [(("GET", "/v1/health"), 503), (("POST", "/v1/parse/jobs"), 429), (("POST", "/v1/uploads"), 500)],
)
def test_a_service_busy_or_failing_is_unavailable_and_the_task_retries(route, status) -> None:
    service = FakeMinerU()
    service.answers[route] = httpx.Response(status, json={"error": {"type": "engine_error", "message": "busy"}})

    with pytest.raises(ExtractionUnavailable, match="busy"):
        reader(service).read(PDF, REQUEST)


def test_a_service_that_cant_be_reached_is_unavailable() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ExtractionUnavailable, match="can't be reached"):
        MinerUReader(URL, transport=httpx.MockTransport(refused)).read(PDF, REQUEST)


def test_a_request_the_service_refuses_fails() -> None:
    service = FakeMinerU()
    service.answers[("POST", "/v1/parse/jobs")] = httpx.Response(
        400, json={"error": {"type": "invalid_request_error", "message": "Tier 'standard' not available"}}
    )

    with pytest.raises(ExtractionFailed, match="not available"):
        reader(service).read(PDF, REQUEST)


def test_a_job_still_running_at_the_deadline_is_unavailable() -> None:
    service = FakeMinerU(statuses=["running"] * 3)
    times = iter([0.0, 10.0, WAIT_SECONDS + 1])

    with pytest.raises(ExtractionUnavailable, match="still running"):
        reader(service, clock=lambda: next(times)).read(PDF, REQUEST)


def test_an_upload_url_on_another_origin_is_refused() -> None:
    service = FakeMinerU()
    pending = service._upload("pending") | {"upload_url": "http://elsewhere.test/upload"}
    service.answers[("POST", "/v1/uploads")] = httpx.Response(200, json=pending)

    with pytest.raises(ExtractionFailed, match="another origin"):
        reader(service, api_key="secret").read(PDF, REQUEST)
    assert all(request.url.host == "mineru.test" for request in service.sent)
