"""Files for the adapter tests: a PDF made with PyMuPDF, and MinerU's Middle JSON for a page of Perpres 10/2021.

`fixtures/mineru/middle_json.json` was written by hand to MinerU 4.0.12's schema and validates against its own
model (`docvortex.schema.MiddleJson.from_dict`, docvortex 0.5.16).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pymupdf

FIXTURES = Path(__file__).parent / "fixtures" / "mineru"
A4 = (595, 842)


def middle_json() -> dict[str, Any]:
    return copy.deepcopy(json.loads((FIXTURES / "middle_json.json").read_text(encoding="utf-8")))


def pdf(*lines: tuple[float, float, str]) -> bytes:
    """A one-page A4 PDF with each `(x, y, text)` written where it says, in points from the top left."""
    document = pymupdf.open()
    page = document.new_page(width=A4[0], height=A4[1])
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=11)
    return document.tobytes()


def regulation_pdf() -> bytes:
    """A page with a running head, an article set word by word on its baseline, and the print serial."""
    words = [(70 + 70 * index, 230, word) for index, word in enumerate(["Setiap", "Pelaku", "Usaha", "wajib"])]
    return pdf(
        (250, 50, "BANK INDONESIA"),
        (70, 200, "Pasal 5"),
        *words,
        (70, 245, "memiliki izin."),
        (70, 800, "SK No 054949 C"),
    )
