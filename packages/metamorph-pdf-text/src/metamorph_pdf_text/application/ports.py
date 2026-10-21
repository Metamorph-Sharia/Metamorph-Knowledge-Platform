"""What the use case needs from outside: a reader that lays a PDF out, and somewhere to keep what it read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from metamorph_pdf_text.application.reading import Reading, ReadRequest


class LayoutReader(Protocol):
    engine: str  # "mineru", "pymupdf"
    version: str  # the engine's exact version: a reading is only reproducible with it

    def read(self, pdf: bytes, request: ReadRequest) -> Reading:
        """Raises ExtractionUnavailable (retry later) or ExtractionFailed."""
        ...


@dataclass(frozen=True)
class CacheKey:
    pdf_sha256: str
    engine: str
    version: str
    request: ReadRequest


class ResultCache(Protocol):
    def get(self, key: CacheKey) -> Reading | None: ...

    def put(self, key: CacheKey, reading: Reading) -> None: ...
