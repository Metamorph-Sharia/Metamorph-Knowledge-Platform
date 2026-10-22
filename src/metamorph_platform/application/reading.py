"""Reading a document's text as the parser cut it (domain/reading.py), a part at a time, laid out for reading
(domain/layout.py): a query, no rule decides anything here. The text's effective wording is read from the object
store, so the reading is what the publish gate checked and what the assistant cites."""

from __future__ import annotations

from typing import Protocol

from metamorph_platform.application.ports import BlobReader
from metamorph_platform.application.views import (
    PageStart,
    PassageReference,
    ReadingBlock,
    ReadingPassage,
    ReadingProvision,
    ReadingSource,
    TextReading,
)
from metamorph_platform.domain.cross_references import cross_references
from metamorph_platform.domain.layout import Block, layout
from metamorph_platform.domain.reading import Passage, list_depth, parts, passages, split_long, utf16_offsets

PART_BUDGET = 200_000  # characters a part: nine texts in ten are read whole (the median is 35,000)


class ReadableTexts(Protocol):
    def reading_source(self, document_id: str, sha256: str | None) -> ReadingSource | None: ...


class ReadText:
    budget = PART_BUDGET

    def __init__(self, texts: ReadableTexts, reader: BlobReader) -> None:
        self.texts, self.reader = texts, reader

    def read(
        self, document_id: str, sha256: str | None = None, *, part: int = 0, at: str | None = None
    ) -> TextReading | None:
        """The part asked for, or the one `at` (an address) opens in; None if there is no such text."""
        source = self.texts.reading_source(document_id, sha256)
        if source is None:
            return None
        text = self.reader.read(source.storage_key).decode("utf-8")
        read = split_long(passages(text, source.provisions), self.budget)
        numbers = parts(read, self.budget)
        opened_in = {p.address: n for p, n in zip(read, numbers, strict=True) if p.opens}
        last = numbers[-1] if numbers else 0
        shown = min(max(opened_in.get(at, part) if at else part, 0), last)
        return TextReading(
            document_id=source.document_id,
            citation=source.citation,
            title=source.title,
            sha256=source.sha256,
            problems=source.problems,
            corrected=source.corrected,
            editable=source.editable,
            pdf_sha256=source.pdf_sha256,
            texts=source.texts,
            part=shown,
            parts=last + 1,
            provisions=_outline(source, text, opened_in),
            passages=_laid_out(
                [p for p, n in zip(read, numbers, strict=True) if n == shown],
                {p.address for p in source.provisions},
            ),
        )


def _laid_out(shown: list[Passage], addresses: set[str]) -> tuple[ReadingPassage, ...]:
    """Each passage laid out for reading (domain/layout.py), each block with its references to the text's other
    provisions (domain/cross_references.py)."""
    return tuple(
        ReadingPassage(
            passage.address,
            passage.opens,
            passage.titled,
            tuple(
                _block(block, passage.address, addresses, list_depth(passage.address)) for block in layout(passage.text)
            ),
        )
        for passage in shown
    )


def _block(block: Block, within: str | None, addresses: set[str], nested: int) -> ReadingBlock:
    """`nested`: how deep the passage's own list sits; a list in its wording sits deeper still."""
    found = cross_references(block.text, within=within, addresses=addresses)
    offsets = {at for at, _ in block.pages} | {offset for each in found for offset in (each.start, each.end)}
    units = utf16_offsets(block.text, offsets)
    return ReadingBlock(
        block.text,
        block.marker,
        block.depth + nested if block.marker else block.depth,
        tuple(PageStart(units[at], page) for at, page in block.pages),
        tuple(PassageReference(units[each.start], units[each.end], each.address) for each in found),
    )


def _outline(source: ReadingSource, text: str, opened_in: dict[str | None, int]) -> tuple[ReadingProvision, ...]:
    offsets = utf16_offsets(text, {o for p in source.provisions for o in (p.char_start, p.char_end)})
    depth: dict[str, int] = {}
    outline = []
    for p in source.provisions:
        depth[p.address] = depth[p.parent_address] + 1 if p.parent_address in depth else 0
        outline.append(
            ReadingProvision(
                p.address, p.parent_address, p.kind, p.label, p.heading, depth[p.address],
                opened_in.get(p.address, 0), p.page_start, p.page_end, p.valid_to, p.changes,
                offsets[p.char_start], offsets[p.char_end],
            )
        )  # fmt: skip
    return tuple(outline)
