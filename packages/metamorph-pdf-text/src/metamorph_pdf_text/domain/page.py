"""A page as a reader laid it out: its blocks in reading order, each with what it is and where it sits.

A reader (MinerU, PyMuPDF) is translated into these types at its adapter, so nothing past it knows the reader's
own format. A block's text keeps the reader's line breaks; a table's rows are its lines and its cells are
separated by tabs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class BlockKind(StrEnum):
    TITLE = "title"
    TEXT = "text"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    ASIDE = "aside"
    IMAGE = "image"
    FORMULA = "formula"


MARKED_FURNITURE = frozenset({BlockKind.HEADER, BlockKind.FOOTER, BlockKind.PAGE_NUMBER, BlockKind.ASIDE})


@dataclass(frozen=True)
class BBox:
    """In points from the page's top left corner, as PDF readers report it."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    bbox: BBox

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def with_lines(self, lines: list[str]) -> Block:
        return replace(self, text="\n".join(lines))


@dataclass(frozen=True)
class Page:
    number: int  # from 1, as the page markers count
    width: float
    height: float
    blocks: tuple[Block, ...]

    def with_blocks(self, blocks: list[Block]) -> Page:
        return replace(self, blocks=tuple(blocks))
