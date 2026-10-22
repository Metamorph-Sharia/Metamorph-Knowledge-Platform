"""`LayoutReader` over a self-hosted MinerU service's V1 API (`mineru-kit api-server`, MinerU 4.0).

    POST /v1/uploads                      filename, bytes, mime_type, sha256sum: a file it holds comes back done
    PUT  {upload_url}                     the bytes, otherwise; then POST /v1/uploads/{id}/complete
    POST /v1/parse/jobs                   files[{source: {type: file_id}}], tier, ocr_mode, output_formats
    GET  /v1/parse/jobs/{job_id}          polled until completed, partial, failed or canceled
    GET  /v1/files/{file_id}/content      the job's middle_json, translated by mineru_layout
    GET  /v1/health, /v1/tiers            the version it runs (pinned) and the tiers it serves

The service's request models reject unknown fields, so the requests carry only these. A service that can't be
reached, is busy (429) or failing (5xx) raises ExtractionUnavailable, so the task retries; a request it refuses
or a file it can't parse raises ExtractionFailed. Only the pinned MinerU version is read: another version reads
documents differently, and texts would change without anyone choosing it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from metamorph_pdf_text.adapters.mineru_layout import reading_from_middle_json
from metamorph_pdf_text.application.reading import ExtractionFailed, ExtractionUnavailable, Reading, ReadRequest, Tier

MINERU_VERSION = "4.0.12"
TRANSLATION = 1  # bump when mineru_layout reads Middle JSON differently: the version changes, cached readings go
REQUEST_SECONDS = 300.0  # one request; uploading an 81 MB BPK file takes a while
POLL_SECONDS = 5.0
WAIT_SECONDS = 4 * 3600.0  # for one job: BPK's longest file has 1,187 pages
DONE = frozenset({"completed", "partial", "failed", "canceled"})
_BUSY = 429
_SERVER_ERROR = 500


class MinerUReader:
    engine = "mineru"

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._base = url.rstrip("/") + "/"
        self._client = httpx.Client(base_url=self._base, headers=headers, timeout=REQUEST_SECONDS, transport=transport)
        self._sleep, self._clock = sleep, clock
        self._version: str | None = None

    @property
    def version(self) -> str:
        """The service's MinerU version and this translation's: a reading is only reproducible with both."""
        return self._pinned()

    def tiers(self) -> frozenset[Tier]:
        """The tiers this reader asks for that the service serves: `--tier standard` serves both."""
        served = {tier["id"] for tier in self._json("GET", "v1/tiers")["data"]}
        return frozenset(tier for tier in Tier if tier in served)

    def read(self, pdf: bytes, request: ReadRequest) -> Reading:
        self._pinned()  # another MinerU is refused before it is sent anything
        job = self._json("POST", "v1/parse/jobs", json=_job(self._uploaded(pdf), request))
        middle_json = self._call("GET", f"v1/files/{_middle_json_of(self._finished(job['job_id']))}/content")
        return reading_from_middle_json(json.loads(middle_json.content))

    def _pinned(self) -> str:
        if self._version is None:
            running = self._json("GET", "v1/health")["version"]
            if running != MINERU_VERSION:
                raise ExtractionFailed(f"MinerU {running} is running; this reader reads MinerU {MINERU_VERSION}")
            self._version = f"{running}+t{TRANSLATION}"
        return self._version

    def _uploaded(self, pdf: bytes) -> str:
        """The service's file id for `pdf`, uploading it unless the service already holds it."""
        sha256 = hashlib.sha256(pdf).hexdigest()
        upload = self._json(
            "POST",
            "v1/uploads",
            json={"filename": f"{sha256}.pdf", "bytes": len(pdf), "mime_type": "application/pdf", "sha256sum": sha256},
        )
        if upload["status"] != "completed":
            self._call(
                "PUT", self._same_origin(upload["upload_url"]), content=pdf, headers=upload.get("upload_headers")
            )
            upload = self._json("POST", f"v1/uploads/{upload['id']}/complete", json={"sha256sum": sha256})
        return upload["file"]["id"]

    def _finished(self, job_id: str) -> Mapping[str, Any]:
        deadline = self._clock() + WAIT_SECONDS
        while (job := self._json("GET", f"v1/parse/jobs/{job_id}"))["status"] not in DONE:
            if self._clock() >= deadline:
                raise ExtractionUnavailable(f"MinerU job {job_id} still {job['status']} after {WAIT_SECONDS:.0f} s")
            self._sleep(POLL_SECONDS)
        return job

    def _same_origin(self, url: str) -> str:
        """An upload URL on this service: the API key is never sent elsewhere."""
        absolute = urljoin(self._base, url)
        if urlsplit(absolute)[:2] != urlsplit(self._base)[:2]:
            raise ExtractionFailed(f"MinerU asked for the upload at another origin: {absolute}")
        return absolute

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._call(method, path, **kwargs).json()

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TransportError as error:
            raise ExtractionUnavailable(f"MinerU at {self._base} can't be reached: {error!r}") from error
        if response.status_code == _BUSY or response.status_code >= _SERVER_ERROR:
            raise ExtractionUnavailable(f"MinerU {method} {path}: {response.status_code} {_message(response)}")
        if response.is_error:
            raise ExtractionFailed(f"MinerU {method} {path}: {response.status_code} {_message(response)}")
        return response


def _job(file_id: str, request: ReadRequest) -> dict[str, Any]:
    return {
        "files": [{"source": {"type": "file_id", "file_id": file_id}}],
        "tier": str(request.tier),
        "ocr_mode": str(request.ocr_mode),
        "output_formats": ["middle_json"],
    }


def _middle_json_of(job: Mapping[str, Any]) -> str:
    (result,) = job["files"]
    if job["status"] != "completed" or result["status"] != "completed":
        error = (result.get("error") or {}).get("message", "no error given")
        raise ExtractionFailed(f"MinerU job {job['job_id']} {job['status']}: {error}")
    return result["output_files"]["middle_json"]["file_id"]


def _message(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:200]
