"""A PDF page's text a printed line to a line, from PyMuPDF's layout of the page.

PyMuPDF's plain text (`page.get_text()`) ends a line wherever the PDF moves its pen. A justified line that the
PDF sets word by word, the gaps wide, comes out a word to a line; a list's number set apart from its text
("1.   Uang Rupiah …") comes out on a line of its own. Its layout (`page.get_text("dict")`) says where each of
those lines sits: lines of one block on one baseline, each to the right of the last, are one printed line, and
are joined by a space. Nothing else changes: the characters, their order and every other line break are the
plain text's. Measured on BI's bi:padg:2026:232026 (76 pages), the joining takes 6,118 lines to 4,334.

The text is always the plain text; the layout only says which of its line breaks to join. When the layout's
lines aren't the text's (some BI FAQ files set glyphs with no width, which the layout leaves out), the page
stays as the plain text has it. The layout is read as plain data (blocks → lines → spans), so the contract
doesn't depend on PyMuPDF.

A connector extracts printed lines unless `METAMORPH_PDF_LINES=extracted` asks for PyMuPDF's own, as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LINES_SETTING = "METAMORPH_PDF_LINES"
PRINTED, EXTRACTED = "printed", "extracted"

_TEXT_BLOCK = 0
# How far apart two baselines may be and still be one, as a share of the smaller font size: words set one by
# one share their baseline exactly, while a raised footnote number sits a third of its size or more above it.
_SAME_BASELINE = 0.2
_STRAIGHT = 1e-3  # how far a line's direction may be off left-to-right and still be read as it


def wants_printed_lines(environment: Mapping[str, str]) -> bool:
    """Whether to extract printed lines (the default) or PyMuPDF's own (`METAMORPH_PDF_LINES=extracted`)."""
    value = environment.get(LINES_SETTING, PRINTED)
    if value not in (PRINTED, EXTRACTED):
        raise ValueError(f"{LINES_SETTING} must be {PRINTED!r} or {EXTRACTED!r}, not {value!r}")
    return value == PRINTED


def printed_text(text: str, layout: Mapping[str, Any]) -> str:
    """`text` (the page's `get_text()`) with each printed line on one line, as `layout` (its "dict") shows them."""
    laid_out = [
        (number, line, "".join(span["text"] for span in line["spans"]))
        for number, block in enumerate(layout["blocks"])
        if block["type"] == _TEXT_BLOCK
        for line in block["lines"]
    ]
    if "".join(f"{words}\n" for _, _, words in laid_out) != text:
        return text  # the layout doesn't hold the text's lines, so it can't say which to join
    out: list[str] = []
    previous = None  # the last line with words, and its block
    for number, line, words in laid_out:
        if previous is not None and previous[0] == number and _continues(previous[1], line):
            out[-1] += ("" if out[-1][-1:].isspace() or words[:1].isspace() else " ") + words
        else:
            out.append(words)
        previous = (number, line) if line["spans"] else None
    return "".join(f"{words}\n" for words in out)


def _continues(previous: Mapping[str, Any], line: Mapping[str, Any]) -> bool:
    """`line` carries on `previous`'s printed line: same baseline, further right, both written left to right."""
    if not line["spans"] or not _horizontal(line) or not _horizontal(previous):
        return False
    before, after = previous["spans"][-1], line["spans"][0]
    tolerance = _SAME_BASELINE * min(before["size"], after["size"])
    return abs(after["origin"][1] - before["origin"][1]) <= tolerance and line["bbox"][0] >= previous["bbox"][2]


def _horizontal(line: Mapping[str, Any]) -> bool:
    cos, sin = line["dir"]
    return abs(cos - 1) <= _STRAIGHT and abs(sin) <= _STRAIGHT
