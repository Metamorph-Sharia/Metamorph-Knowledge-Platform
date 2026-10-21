"""A PDF read into clean pages of text: by a layout reader (MinerU), checked page by page against the PDF's own
text layer, which a page falls back to when the reading can't be trusted.

    1  the text layer is read (the reference) and its quality decides the request (policy.request_for)
    2  the layout reader reads the file, or the cache gives what it read before
    3  both readings are cleaned and written out (domain.cleaning, domain.rendering)
    4  each page keeps the layout reader's text when
         it read the PDF's characters (txt) and holds the layer's words, in any order: a vision model must not
           reword a born-digital page. A word one reading's cleaning logged as furniture doesn't count;
         it read the page image (ocr) and is no noisier than the layer, and not empty where the layer has text
       and falls back to the text layer otherwise. Every fallback is counted in the extraction.
       A page with no text layer at all (a born-digital file's scanned signing page) has no wording to hold: the
       reader OCRs its picture even when it reads the rest from the characters, and it is checked as OCR is.

A reader that can't be reached raises, and nothing falls back: a text read now by one engine and next time by
the other would change at every run.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from metamorph_pdf_text.application.policy import request_for
from metamorph_pdf_text.application.ports import CacheKey, LayoutReader, ResultCache
from metamorph_pdf_text.application.reading import OcrMode, Reading, ReadRequest, Tier
from metamorph_pdf_text.domain.alignment import aligned, words
from metamorph_pdf_text.domain.cleaning import Removal, clean
from metamorph_pdf_text.domain.page import Page
from metamorph_pdf_text.domain.quality import page_quality
from metamorph_pdf_text.domain.rendering import render

TEXT_LAYER, OCR = "text_layer", "ocr"  # contract v2's text methods
_TEXT_LAYER_REQUEST = ReadRequest(Tier.BASIC, OcrMode.TXT)


@dataclass(frozen=True)
class Extraction:
    """How a text was read: kept with it (contract v2.1's TextRef.extraction), so it can be read again alike."""

    engine: str
    engine_version: str
    tier: Tier
    ocr_mode: OcrMode
    pages_ocrd: int
    pages_fallen_back: int


@dataclass(frozen=True)
class ExtractedPdf:
    pages: tuple[str, ...]  # one a page, in order: for metamorph_contract.join_pages
    method: str  # TEXT_LAYER, or OCR when any page kept is the reader's OCR
    extraction: Extraction
    removals: tuple[Removal, ...]  # what cleaning took off the pages kept, for the audit report


class ExtractPdf:
    def __init__(
        self, reader: LayoutReader, text_layer: LayoutReader, cache: ResultCache, vocabulary: Collection[str]
    ) -> None:
        self._reader = reader
        self._text_layer = text_layer
        self._cache = cache
        self._vocabulary = vocabulary  # the lowercased words of clean texts, for page_quality

    def run(self, pdf: bytes, role: str) -> ExtractedPdf:
        layer = _Written.of(self._text_layer.read(pdf, _TEXT_LAYER_REQUEST).pages)
        request = request_for(role, [page_quality(text, self._vocabulary) for text in layer.texts.values()])
        reading = self._read(pdf, request)
        read = _Written.of(reading.pages, from_images=_from_images(reading.ocr_mode, layer))
        chosen = {
            number: read if self._trusted(reading.ocr_mode, number, read, layer) else layer for number in layer.texts
        }
        ocrd = sum(source is read and _ocrd(reading.ocr_mode, number, read, layer) for number, source in chosen.items())
        fallen_back = sum(source is layer for source in chosen.values())
        return ExtractedPdf(
            pages=tuple(source.texts[number] for number, source in chosen.items()),
            method=OCR if ocrd else TEXT_LAYER,
            extraction=Extraction(
                self._reader.engine, self._reader.version, request.tier, reading.ocr_mode, ocrd, fallen_back
            ),
            removals=tuple(removal for number, source in chosen.items() for removal in source.removals.get(number, [])),
        )

    def _read(self, pdf: bytes, request: ReadRequest) -> Reading:
        key = CacheKey(hashlib.sha256(pdf).hexdigest(), self._reader.engine, self._reader.version, request)
        reading = self._cache.get(key)
        if reading is None:
            reading = self._reader.read(pdf, request)
            self._cache.put(key, reading)
        return reading

    def _trusted(self, mode: OcrMode, number: int, read: _Written, layer: _Written) -> bool:
        if number not in read.texts:
            return False
        if _ocrd(mode, number, read, layer):
            return self._no_noisier(read.texts[number], layer.texts[number])
        return _keeps_wording(number, read, layer)

    def _no_noisier(self, candidate: str, layer_text: str) -> bool:
        ocr, layer = page_quality(candidate, self._vocabulary), page_quality(layer_text, self._vocabulary)
        if not layer.characters:
            return True  # a scan: the OCR is all there is
        if not ocr.characters:
            return False
        return layer.is_noisy or not ocr.is_noisy


def _from_images(mode: OcrMode, layer: _Written) -> set[int]:
    """The pages the reader read from their images: every page when it OCRs, else those with no text layer."""
    return {number for number, text in layer.texts.items() if mode is OcrMode.OCR or not text.strip()}


def _ocrd(mode: OcrMode, number: int, read: _Written, layer: _Written) -> bool:
    """Whether the reader's text of a page came from its image: OCR, or text found on a page with no text layer."""
    return mode is OcrMode.OCR or (not layer.texts[number].strip() and bool(read.texts.get(number, "").strip()))


def _keeps_wording(number: int, read: _Written, layer: _Written) -> bool:
    alignment = aligned(read.texts[number], layer.texts[number])
    missing = alignment.missing - read.removed_words(number)
    added = alignment.added - layer.removed_words(number)
    return not missing and not added


@dataclass(frozen=True)
class _Written:
    """A reading cleaned and written out: each page's text, and what cleaning took off it, by page number."""

    texts: dict[int, str]
    removals: dict[int, list[Removal]]

    @classmethod
    def of(cls, pages: Sequence[Page], from_images: Collection[int] = ()) -> _Written:
        cleaned = clean(pages, from_images)
        removals: dict[int, list[Removal]] = {}
        for removal in cleaned.removals:
            removals.setdefault(removal.page, []).append(removal)
        numbers = (page.number for page in cleaned.pages)
        return cls(dict(zip(numbers, render(cleaned.pages), strict=True)), removals)

    def removed_words(self, number: int) -> Counter[str]:
        return sum((words(removal.text) for removal in self.removals.get(number, [])), Counter())
