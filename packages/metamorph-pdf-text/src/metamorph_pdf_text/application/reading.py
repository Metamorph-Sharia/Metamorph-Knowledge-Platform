"""What a reader is asked for and what it gives back: the data that crosses the port to a reader."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metamorph_pdf_text.domain.page import Page


class Tier(StrEnum):
    BASIC = "basic"  # small OCR and layout models
    STANDARD = "standard"  # small models and a vision-language model: complex layouts


class OcrMode(StrEnum):
    AUTO = "auto"  # the reader decides, document by document
    TXT = "txt"  # the PDF's own characters
    OCR = "ocr"  # the page images


@dataclass(frozen=True)
class ReadRequest:
    tier: Tier
    ocr_mode: OcrMode


@dataclass(frozen=True)
class Reading:
    pages: tuple[Page, ...]
    ocr_mode: OcrMode  # as resolved: TXT or OCR, never AUTO


class ExtractionUnavailable(Exception):
    """The reader can't be reached now (a service down, a timeout): retry the task later."""


class ExtractionFailed(Exception):
    """The reader can't read this file."""
