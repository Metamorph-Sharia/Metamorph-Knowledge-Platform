"""Cleaned pages written out as plain text, a block laid out as the reader read it.

    a block is a paragraph   its lines joined by spaces; a blank line between blocks
    a heading keeps its line a line the reader gave as a heading ("Pasal 5", "BAB IV", "Menimbang :") isn't joined to
                             the wording around it
    an item starts a line    a line opening with "(1)", "a.", "1.", "IV." starts a paragraph
    a title keeps its lines  "BAB I" / "KETENTUAN UMUM" stay two
    a lone marker rejoins    a list marker read as a block of its own, from a column apart ("(4)" in the margin),
                             opens the paragraph level with it, wherever the reader put it
    a table is its rows      one a line, cells separated by " | "

Headings the reader ran onto one line with other text ("BAB I KETENTUAN UMUM Pasal 1", "Pasal 8 Ayat (1) Huruf a
Cukup jelas.") stay as read: legal structure is the parser's (the platform's domain/structure/run_together.py, plan
step 13). Images and formulas carry no wording and are left out. The pages come in the reader's reading order, which
is kept: a two-column page reads one column, then the other.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from metamorph_pdf_text.domain.page import Block, BlockKind, Page
from metamorph_pdf_text.domain.patterns import HEADING_LINE, ITEM_MARKER

WORDLESS = frozenset({BlockKind.IMAGE, BlockKind.FORMULA})
CELL_SEPARATOR = " | "
_LONE_MARKER = re.compile(r"^(?:\(\d{1,3}[a-z]?\)|\d{1,3}[a-z]?[.)]|[a-z][.)])\.?$")


def render(pages: Sequence[Page]) -> list[str]:
    """One text a page, in order; `metamorph_contract.join_pages` adds the page markers."""
    return [_page_text(page) for page in pages]


def _page_text(page: Page) -> str:
    return "\n\n".join(text for text in (_block_text(block) for block in _markers_attached(page.blocks)) if text)


def _markers_attached(blocks: Sequence[Block]) -> list[Block]:
    """Each lone marker joined to the block level with it on its right: its top within half the marker's height."""
    attached = list(blocks)
    for marker in blocks:
        if not _is_lone_marker(marker):
            continue
        tolerance = (marker.bbox.y1 - marker.bbox.y0) / 2
        level = [
            index
            for index, block in enumerate(attached)
            if block.kind not in WORDLESS | {BlockKind.TABLE}
            and not _is_lone_marker(block)
            and block.bbox.x0 >= marker.bbox.x0
            and abs(block.bbox.y0 - marker.bbox.y0) <= tolerance
        ]
        if level:
            paragraph = min(level, key=lambda index: abs(attached[index].bbox.y0 - marker.bbox.y0))
            attached[paragraph] = replace(attached[paragraph], text=f"{marker.text.strip()} {attached[paragraph].text}")
            attached = [block for block in attached if block is not marker]
    return attached


def _is_lone_marker(block: Block) -> bool:
    return bool(_LONE_MARKER.match(block.text.strip()))


def _block_text(block: Block) -> str:
    if block.kind in WORDLESS:
        return ""
    if block.kind is BlockKind.TABLE:
        return "\n".join(CELL_SEPARATOR.join(cell.strip() for cell in row.split("\t")) for row in block.lines)
    if block.kind is BlockKind.TITLE:
        return "\n".join(line for line in block.lines if line.strip())
    return "\n".join(_paragraphs(block.lines))


def _paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    after_heading = False
    for line in lines:
        if not paragraphs or after_heading or _opens_paragraph(line):
            paragraphs.append(line)
        else:
            paragraphs[-1] += " " + line
        after_heading = bool(HEADING_LINE.match(line))
    return paragraphs


def _opens_paragraph(line: str) -> bool:
    return bool(HEADING_LINE.match(line) or ITEM_MARKER.match(line))
