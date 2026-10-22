"""An official file's pages read into clean, laid-out text for a Metamorph connector."""

from metamorph_pdf_text.application.extract_pdf import OCR, TEXT_LAYER, ExtractedPdf, Extraction, ExtractPdf
from metamorph_pdf_text.application.policy import request_for
from metamorph_pdf_text.application.ports import CacheKey, LayoutReader, ResultCache
from metamorph_pdf_text.application.reading import (
    ExtractionFailed,
    ExtractionUnavailable,
    OcrMode,
    Reading,
    ReadRequest,
    Tier,
)
from metamorph_pdf_text.contract import text_extraction, text_method
from metamorph_pdf_text.domain.alignment import Alignment, aligned, respelled
from metamorph_pdf_text.domain.cleaning import Cleaned, Removal, clean
from metamorph_pdf_text.domain.page import BBox, Block, BlockKind, Page
from metamorph_pdf_text.domain.quality import PageQuality, page_quality
from metamorph_pdf_text.domain.rendering import render
from metamorph_pdf_text.environment import SETTINGS, from_environment, wants_mineru

__all__ = [
    "OCR",
    "SETTINGS",
    "TEXT_LAYER",
    "Alignment",
    "BBox",
    "Block",
    "BlockKind",
    "CacheKey",
    "Cleaned",
    "ExtractPdf",
    "ExtractedPdf",
    "Extraction",
    "ExtractionFailed",
    "ExtractionUnavailable",
    "LayoutReader",
    "OcrMode",
    "Page",
    "PageQuality",
    "ReadRequest",
    "Reading",
    "Removal",
    "ResultCache",
    "Tier",
    "aligned",
    "respelled",
    "clean",
    "from_environment",
    "page_quality",
    "render",
    "request_for",
    "text_extraction",
    "text_method",
    "wants_mineru",
]
