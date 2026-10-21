"""Cleaned pages written out as plain text, laid out so the platform's parser sees the structure by the lines.

    a block is a paragraph   its lines joined by spaces; a blank line between blocks
    a heading has its line   "Pasal 5", "BAB IV", "Menimbang :" stand alone, so wording never runs onto them
    an item starts a line    "(1)", "a.", "1.", "IV." open a line, even mid-block
    a title keeps its lines  "BAB I" / "KETENTUAN UMUM" stay two
    a table is its rows      one a line, cells separated by " | "

Images and formulas carry no wording and are left out. The pages come in the reader's reading order, which is
kept: a two-column page reads one column, then the other.
"""

from __future__ import annotations

from collections.abc import Sequence

from metamorph_pdf_text.domain.page import Block, BlockKind, Page
from metamorph_pdf_text.domain.patterns import HEADING_LINE, ITEM_MARKER

WORDLESS = frozenset({BlockKind.IMAGE, BlockKind.FORMULA})
CELL_SEPARATOR = " | "


def render(pages: Sequence[Page]) -> list[str]:
    """One text a page, in order; `metamorph_contract.join_pages` adds the page markers."""
    return [_page_text(page) for page in pages]


def _page_text(page: Page) -> str:
    return "\n\n".join(text for text in (_block_text(block) for block in page.blocks) if text)


def _block_text(block: Block) -> str:
    if block.kind in WORDLESS:
        return ""
    if block.kind is BlockKind.TABLE:
        return "\n".join(CELL_SEPARATOR.join(cell.strip() for cell in row.split("\t")) for row in block.lines)
    if block.kind is BlockKind.TITLE:
        return block.text
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
