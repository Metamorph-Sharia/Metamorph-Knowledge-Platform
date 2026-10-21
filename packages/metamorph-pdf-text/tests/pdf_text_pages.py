"""Pages for the tests, laid out as a reader reports them on an A4 page, from real documents."""

from __future__ import annotations

from metamorph_pdf_text import BBox, Block, BlockKind, Page

WIDTH, HEIGHT = 595.0, 842.0  # A4, in points
TOP = BBox(70, 30, 525, 80)  # inside the top band (12% of the height: 101 pt)
BODY = BBox(70, 120, 525, 700)
FOOT = BBox(70, 770, 525, 815)  # inside the foot band (from 741 pt)


def block(text: str, where: BBox = BODY, kind: BlockKind = BlockKind.TEXT) -> Block:
    return Block(kind, text, where)


def page(number: int, *blocks: Block) -> Page:
    return Page(number, WIDTH, HEIGHT, tuple(blocks))


def annex_page(number: int, head: str = "PRES I DEN\nREPUBLIK INDONESIA") -> Page:
    """A page of Perpres 10/2021's investment list, as its text layer reads (BPK, text_version 1000, page 3):
    the running head and printed page number on top, the serial and a catchword at the foot."""
    return page(
        number,
        block(f"{head}\n-{number}-", TOP),
        block(f"{20 + number}. Angkutan sungai dan danau untuk barang umum\nModal asing maksimal 49%"),
        block(f"SK No 0549{number:02d} C\n{21 + number}. Angkutan .", FOOT),
    )
