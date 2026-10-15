"""Turns "a heading at this level starts here" into a tree with spans: the grammars only recognise headings.

Levels go down the hierarchy: 0 a section (penjelasan, lampiran), 1 a chapter, … 6 a quoted paragraph.
Opening a node closes every open node at the same or a deeper level. A node ends with its last line of
content, so the page break and running page number before the next heading stay out of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from metamorph_platform.domain.structure.model import Node
from metamorph_platform.domain.structure.text import Line, Pages

MAX_HEADING_LENGTH = 150


@dataclass
class _Open:
    level: int
    address: str
    kind: str
    label: str
    start: int
    ordinal: int
    parent: str | None
    heading: str | None
    end: int = -1


class TreeBuilder:
    def __init__(self, text: str) -> None:
        self.text = text
        self._open: list[_Open] = []
        self._all: list[_Open] = []
        self._addresses: set[str] = set()
        self._awaiting_heading: _Open | None = None
        self._content_end = 0

    def passed(self, line: Line) -> None:
        """Called for every content line, after the grammar has seen it."""
        self._content_end = line.end

    def empty(self) -> bool:
        return not self._all

    def has(self, address: str) -> bool:
        return address in self._addresses

    def open(
        self, level: int, address: str, kind: str, label: str, line: Line, *, heading: str | None = None,
        expects_heading: bool = False,
    ) -> bool:  # fmt: skip
        """False, and nothing opened, when the address exists already: a repeated running header, say.

        `expects_heading`: a bare heading ("BAB II") is named by the next line ("KEGIATAN USAHA").
        """
        if address in self._addresses:
            return False
        self.close(level)
        node = _Open(level, address, kind, label, line.start, len(self._all), self._parent(), heading or None)
        self._open.append(node)
        self._all.append(node)
        self._addresses.add(address)
        self._awaiting_heading = node if expects_heading and not heading else None
        return True

    def rename_last(self, address: str, label: str) -> None:
        """Correct the node just opened, before anything is nested in it (a misread heading)."""
        node = self._all[-1]
        self._addresses.discard(node.address)
        node.address, node.label = address, label
        self._addresses.add(address)

    def take_heading(self, line: Line) -> bool:
        """The line after a bare heading ("BAB II" / "KEGIATAN USAHA") names it. True if it was used so."""
        node, self._awaiting_heading = self._awaiting_heading, None
        if node is None or len(line.text) > MAX_HEADING_LENGTH:
            return False
        node.heading = line.text
        return True

    def close(self, level: int) -> None:
        self._awaiting_heading = None
        while self._open and self._open[-1].level >= level:
            self._open.pop().end = self._content_end

    def nodes(self) -> tuple[Node, ...]:
        self.close(0)
        pages = Pages(self.text)
        return tuple(
            Node(
                address=node.address,
                kind=node.kind,
                label=node.label,
                char_start=node.start,
                char_end=node.end,
                ordinal=node.ordinal,
                parent=node.parent,
                heading=node.heading,
                page_start=pages.at(node.start),
                page_end=pages.at(max(node.start, node.end - 1)),
            )
            for node in self._all
        )

    def _parent(self) -> str | None:
        return self._open[-1].address if self._open else None
