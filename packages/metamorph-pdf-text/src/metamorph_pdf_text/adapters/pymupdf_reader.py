"""`LayoutReader` over a PDF's own text layer, with PyMuPDF: the reference a layout reader's page is checked
against, and the page it falls back to.

Each text block of PyMuPDF's layout is a block, its lines joined where they are one printed line
(`metamorph_contract.printed_text`). When the layout doesn't hold the page's text (some BI FAQ files set glyphs
with no width, which the layout leaves out), the page is one block of its plain text: no word may be missing
from the reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pymupdf
from metamorph_contract import printed_text

from metamorph_pdf_text.application.reading import ExtractionFailed, OcrMode, Reading, ReadRequest
from metamorph_pdf_text.domain.page import BBox, Block, BlockKind, Page

pymupdf.TOOLS.mupdf_display_errors(False)  # MuPDF prints parser warnings to stdout

_TEXT_BLOCK = 0


class PyMuPdfReader:
    engine = "pymupdf"
    version = pymupdf.VersionBind

    def read(self, pdf: bytes, request: ReadRequest) -> Reading:
        """The text layer, whatever `request` asks: PyMuPDF reads no images."""
        try:
            document = pymupdf.open(stream=pdf, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
            raise ExtractionFailed(f"unreadable PDF: {error}") from error
        with document:
            return Reading(tuple(_page(number, page) for number, page in enumerate(document, start=1)), OcrMode.TXT)


def _page(number: int, page: pymupdf.Page) -> Page:
    text = page.get_text()
    layout = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    blocks = [block for block in layout["blocks"] if block["type"] == _TEXT_BLOCK]
    width, height = page.rect.width, page.rect.height
    if "".join(_lines(block) for block in blocks) != text:
        whole = (Block(BlockKind.TEXT, text.strip(), BBox(0, 0, width, height)),) if text.strip() else ()
        return Page(number, width, height, whole)
    return Page(number, width, height, tuple(_block(block) for block in blocks if _lines(block).strip()))


def _block(block: Mapping[str, Any]) -> Block:
    joined = printed_text(_lines(block), {"blocks": [block]})
    return Block(BlockKind.TEXT, joined.rstrip("\n"), BBox(*block["bbox"]))


def _lines(block: Mapping[str, Any]) -> str:
    """The block's text as the page's plain text holds it: a line each, as printed_text reads it."""
    return "".join("".join(span["text"] for span in line["spans"]) + "\n" for line in block["lines"])
