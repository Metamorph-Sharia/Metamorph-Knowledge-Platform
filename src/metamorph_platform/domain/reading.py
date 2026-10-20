"""A text read as the structure parser cut it: what a curator sees when checking the parser's work.

A provision's range holds its children's (an article holds its paragraphs), so each character is read once, in
the innermost provision that holds it. The result is a list of passages in reading order. A provision's first
passage "opens" it: that is where its heading goes. Heading lines ("Pasal 2", "BAB I" and its title) are taken
off the text, because the reader shows them as headings. A heading that shares its line with the wording
("Menimbang : a. …", "(1) Perusahaan …") stays in the text.

A long text is read in parts of a bounded size, so no page carries 1.5 MB at once.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

ASTRAL = 0xFFFF  # beyond it, a character takes two UTF-16 units: an editor counts it twice


class Located(Protocol):
    address: str
    parent_address: str | None
    label: str
    heading: str | None
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Passage:
    address: str | None  # None: text outside every provision (a title, a closing)
    text: str
    opens: bool  # the provision's first passage: where its heading goes
    titled: bool = False  # its heading lines were taken off the text: show the label and heading instead


def passages(text: str, provisions: Sequence[Located]) -> list[Passage]:
    known = {provision.address for provision in provisions}
    children: dict[str | None, list[Located]] = {}
    for provision in sorted(provisions, key=lambda each: each.char_start):
        parent = provision.parent_address if provision.parent_address in known else None
        children.setdefault(parent, []).append(provision)
    read: list[Passage] = []

    def own(provision: Located, piece: str, *, opened: bool) -> None:
        if not opened:
            wording, titled = _without_heading(piece, provision)
            read.append(Passage(provision.address, wording, opens=True, titled=titled))
        elif piece.strip():
            read.append(Passage(provision.address, piece, opens=False))

    def enter(provision: Located) -> None:
        cursor, opened = provision.char_start, False
        for child in children.get(provision.address, []):
            own(provision, text[cursor : child.char_start], opened=opened)
            opened = True
            enter(child)
            cursor = max(cursor, child.char_end)
        own(provision, text[cursor : provision.char_end], opened=opened)

    cursor = 0
    for root in children.get(None, []):
        _outside(read, text[cursor : root.char_start])
        enter(root)
        cursor = max(cursor, root.char_end)
    _outside(read, text[cursor:])
    return read


def split_long(read: Iterable[Passage], limit: int) -> list[Passage]:
    """Each passage longer than `limit`, cut at line ends into pieces no longer (unless a single line is)."""
    pieces: list[Passage] = []
    for passage in read:
        if len(passage.text) <= limit:
            pieces.append(passage)
            continue
        chunks = _chunks(passage.text, limit)
        pieces.append(replace(passage, text=chunks[0]))
        pieces.extend(Passage(passage.address, chunk, opens=False) for chunk in chunks[1:])
    return pieces


def parts(read: Sequence[Passage], budget: int) -> list[int]:
    """The part each passage falls in: consecutive passages, up to `budget` characters a part, one at least."""
    numbers, part, size = [], 0, 0
    for passage in read:
        if size and size + len(passage.text) > budget:
            part, size = part + 1, 0
        numbers.append(part)
        size += len(passage.text)
    return numbers


def utf16_offsets(text: str, offsets: Iterable[int]) -> dict[int, int]:
    """Each character offset, counted as an editor counts (CodeMirror, the browser): in UTF-16 units."""
    astral = [index for index, character in enumerate(text) if ord(character) > ASTRAL]
    return {offset: offset + bisect_left(astral, offset) for offset in offsets}


def _outside(read: list[Passage], piece: str) -> None:
    if piece.strip():
        read.append(Passage(None, piece, opens=False))


def _without_heading(piece: str, provision: Located) -> tuple[str, bool]:
    names = {_name(name) for name in (provision.label, provision.heading) if name}
    lines = piece.splitlines(keepends=True)
    taken = 0
    while taken < len(lines) and _name(lines[taken]) in names:
        taken += 1
    return "".join(lines[taken:]), taken > 0


def _name(line: str) -> str:
    """A heading line as it compares: "MEMUTUSKAN:" is the heading MEMUTUSKAN."""
    return line.strip().rstrip(":").strip().casefold()


def _chunks(text: str, limit: int) -> list[str]:
    chunks, chunk = [], ""
    for line in text.splitlines(keepends=True):
        if chunk and len(chunk) + len(line) > limit:
            chunks.append(chunk)
            chunk = ""
        chunk += line
    return [*chunks, chunk] if chunk else chunks
