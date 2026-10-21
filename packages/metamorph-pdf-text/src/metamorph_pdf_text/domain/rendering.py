"""Cleaned pages written out as plain text, laid out so the platform's parser sees the structure by the lines.

    a block is a paragraph   its lines joined by spaces; a blank line between blocks
    a heading has its line   "Pasal 5", "BAB IV", "Menimbang :" stand alone, so wording never runs onto them
    an item starts a line    "(1)", "a.", "1.", "IV." open a line, even mid-block
    a title keeps its lines  "BAB I" / "KETENTUAN UMUM" stay two
    a heading stack splits   read as one line, "BAB I KETENTUAN UMUM Pasal 1" is two, "Paragraf 1 Umum Pasal 2"
                             three: the parser reads "Pasal 1", "Paragraf 1" and "Bagian Kesatu" on lines of their own
    a table is its rows      one a line, cells separated by " | "

Images and formulas carry no wording and are left out. The pages come in the reader's reading order, which is
kept: a two-column page reads one column, then the other.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence

from metamorph_pdf_text.domain.page import Block, BlockKind, Page
from metamorph_pdf_text.domain.patterns import HEADING_LINE, ITEM_MARKER

WORDLESS = frozenset({BlockKind.IMAGE, BlockKind.FORMULA})
CELL_SEPARATOR = " | "
STACK_WORDS = 20  # at most, in a line that is a stack of headings and not a sentence

_HEADING = re.compile(r"\b(?:BAB\s+[IVXLC]+\b|Bagian\s+Ke\w+|Paragraf\s+\d+\b|Pasal\s+(?:\d+[A-Z]?|[IVXLC]+)\b)")
_ALONE = re.compile(r"^(?:Bagian|Paragraf)\b")  # the parser reads them only on a line of their own


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
        return "\n".join(piece for line in block.lines for piece in _heading_stack(line))
    return "\n".join(_paragraphs(block.lines))


def _paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    after_heading = False
    for line in lines:
        pieces = _heading_stack(line)
        for piece in pieces:
            if not paragraphs or after_heading or len(pieces) > 1 or _opens_paragraph(piece):
                paragraphs.append(piece)
            else:
                paragraphs[-1] += " " + piece
            after_heading = bool(HEADING_LINE.match(piece))
    return paragraphs


def _heading_stack(line: str) -> list[str]:
    """A line that is several headings, a heading a line. It starts with a heading, and either ends with an
    article's ("BAB I KETENTUAN UMUM Pasal 1") or starts with a part or section ("Bagian Keempat Pemeriksaan
    Pendahuluan"). A sentence citing an article ("Pasal 5 diubah dan Pasal 6 dihapus") stays as it is."""
    headings = list(_HEADING.finditer(line))
    if not headings or headings[0].start() != 0 or len(line.split()) > STACK_WORDS:
        return [line]
    cuts = {heading.end() for heading in headings if _ALONE.match(heading[0])}
    cuts |= {heading.start() for heading in headings[1:] if _ALONE.match(heading[0]) or heading.end() == len(line)}
    if not cuts - {0, len(line)}:
        return [line]
    bounds = [0, *sorted(cuts), len(line)]
    return [piece for start, end in itertools.pairwise(bounds) if (piece := line[start:end].strip())]


def _opens_paragraph(line: str) -> bool:
    return bool(HEADING_LINE.match(line) or ITEM_MARKER.match(line))
