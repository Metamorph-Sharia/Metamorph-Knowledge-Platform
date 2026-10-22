"""MinerU's Middle JSON (schema "docvortex.middle" 2.0, MinerU 4.0) translated into pages of blocks: the only
place that knows its shape.

    pages[].page_idx                   from 0; a Page is numbered from 1, as the page markers count
    pages[].blocks[]                   in reading order, with a bbox normalised to the page (0 to 1)
    extensions.mineru.parse_mode       "txt" or "ocr": how MinerU read the document

A block's wording is its `content`: a string, a list of inline spans (text, inline equations, code, links holding
spans), or, for lists, tables and images, a list of child blocks. A list becomes one block an item; a table its
body's rows (cells separated by tabs) and its captions; an image only its captions. A block type this translation
doesn't know keeps its wording as text, so a newer MinerU can't make words disappear.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from html.parser import HTMLParser
from typing import Any

from metamorph_pdf_text.application.reading import ExtractionFailed, OcrMode, Reading
from metamorph_pdf_text.domain.page import BBox, Block, BlockKind, Page

SCHEMA, SCHEMA_VERSION = "docvortex.middle", "2.0"
WHOLE_PAGE = BBox(0.0, 0.0, 1.0, 1.0)

_KINDS = {
    "doc_title": BlockKind.TITLE,
    "paragraph_title": BlockKind.TITLE,
    "header": BlockKind.HEADER,
    "footer": BlockKind.FOOTER,
    "page_number": BlockKind.PAGE_NUMBER,
    "aside_text": BlockKind.ASIDE,
    "page_footnote": BlockKind.FOOTNOTE,
    "equation": BlockKind.FORMULA,
}
_LISTS = {"list"}
_CONTAINERS = {"index"}  # child blocks read in order, each as itself
_VISUALS = {"table", "image", "chart", "code"}
_WORDLESS_BODIES = {"image_body", "chart_body"}
_INLINE_SPANS = {"text", "equation_inline", "code_inline"}


def reading_from_middle_json(document: Mapping[str, Any]) -> Reading:
    if document.get("schema") != SCHEMA or document.get("schema_version") != SCHEMA_VERSION:
        raise ExtractionFailed(
            f"not {SCHEMA} {SCHEMA_VERSION}: {document.get('schema')} {document.get('schema_version')}"
        )
    try:
        mode = OcrMode(document["extensions"]["mineru"]["parse_mode"])
        if mode is OcrMode.AUTO:
            raise ValueError("parse_mode is the mode asked for, not the one MinerU read with")
        pages = tuple(
            # MinerU leaves out what is default, so a blank page has no "blocks"
            Page(page["page_idx"] + 1, WHOLE_PAGE.x1, WHOLE_PAGE.y1, tuple(_blocks(page.get("blocks", ()), WHOLE_PAGE)))
            for page in document["pages"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ExtractionFailed(f"unexpected Middle JSON: {error!r}") from error
    return Reading(pages, mode)


def _blocks(raw_blocks: Sequence[Mapping[str, Any]], around: BBox) -> Iterator[Block]:
    for raw in raw_blocks:
        bbox = _bbox(raw.get("bbox")) or around
        kind = raw["type"]
        if kind in _LISTS:
            yield from _list_items(raw["content"], bbox)
        elif kind in _CONTAINERS:
            yield from _blocks(raw["content"], bbox)
        elif kind in _VISUALS:
            yield from _visual(raw["content"], bbox)
        elif text := _text(raw.get("content")):
            yield Block(_KINDS.get(kind, BlockKind.TEXT), text, bbox)


def _list_items(children: Sequence[Mapping[str, Any]], around: BBox) -> Iterator[Block]:
    for child in children:
        bbox = _bbox(child.get("bbox")) or around
        if child["type"] in _LISTS:
            yield from _list_items(child["content"], bbox)
        elif text := _text(child.get("content")):
            yield Block(BlockKind.LIST_ITEM, text, bbox)


def _visual(children: Sequence[Mapping[str, Any]], around: BBox) -> Iterator[Block]:
    for child in children:
        bbox = _bbox(child.get("bbox")) or around
        kind = child["type"]
        if kind == "table_body":
            if rows := _table_rows(child.get("content") or ""):
                yield Block(BlockKind.TABLE, "\n".join(rows), bbox)
        elif kind not in _WORDLESS_BODIES and (text := _text(child.get("content"))):
            yield Block(BlockKind.TEXT, text, bbox)  # a caption, a footnote to the table, code


def _text(content: Any) -> str:
    """A block's wording: a string as it is, inline spans joined, child blocks a line each."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    if all(isinstance(item, Mapping) and item.get("type") in _INLINE_SPANS | {"hyperlink"} for item in content):
        return "".join(_span_text(span) for span in content).strip()
    return "\n".join(text for item in content if isinstance(item, Mapping) and (text := _text(item.get("content"))))


def _span_text(span: Mapping[str, Any]) -> str:
    if span["type"] == "hyperlink":
        return "".join(_span_text(child) for child in span["content"])
    return span["content"]


def _bbox(value: Any) -> BBox | None:
    return BBox(*(float(number) for number in value)) if value else None


def _table_rows(html: str) -> list[str]:
    """A table body's HTML (MinerU writes <table><tr><td>…) as rows of tab-separated cells."""
    parser = _TableParser()
    parser.feed(html)
    return ["\t".join(cells) for cells in parser.rows if any(cells)]


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
