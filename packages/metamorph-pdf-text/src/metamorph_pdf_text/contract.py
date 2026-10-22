"""An extraction as contract 2.1 records it, on the text a connector exports (TextRef.method, TextRef.extraction)."""

from __future__ import annotations

from metamorph_contract import Extraction, ExtractionMethod

from metamorph_pdf_text.application.extract_pdf import OCR, ExtractedPdf


def text_method(extracted: ExtractedPdf) -> ExtractionMethod:
    return ExtractionMethod.OCR if extracted.method == OCR else ExtractionMethod.TEXT_LAYER


def text_extraction(extracted: ExtractedPdf) -> Extraction:
    read = extracted.extraction
    return Extraction(
        engine=read.engine,
        engine_version=read.engine_version,
        tier=str(read.tier),
        ocr_mode=str(read.ocr_mode),
        pages_ocrd=read.pages_ocrd,
        pages_fallen_back=read.pages_fallen_back,
    )
