"""A text read as the structure parser cut it: what a curator sees when checking the parser's work.

A provision's range holds its children's (an article holds its paragraphs), so each character is read once, in
the innermost provision that holds it. The result is a list of passages in reading order. A provision's first
passage "opens" it: that is where its heading goes. Heading lines ("Pasal 2", "BAB I" and its title) are taken
off the text, because the reader shows them as headings, and so is a label opening the wording on its line
("Menimbang : a. …", "Pertama 1. Berdasarkan …"). A paragraph's number and an item's letter stay: "(1) Perusahaan …"
and "a. bahwa …" hang from them, at the depth of the list they are in (`list_depth`).

A long text is read in parts of a bounded size, so no page carries 1.5 MB at once.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from metamorph_platform.domain.structure.text import is_page_furniture

ASTRAL = 0xFFFF  # beyond it, a character takes two UTF-16 units: an editor counts it twice
_MARKED = re.compile(r"^(?:ayat|huruf|angka)-")  # an address part whose provision is printed after a marker
_ITEM_LABEL = re.compile(r"^(?:[a-z]|\d{1,3})[.)]$")  # "a.", "1)": an item's marker
ELUCIDATION = "penjelasan"


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


def wording(body: str, provision: Located) -> str:
    """A provision's words, to read or to embed: its body without its heading lines (as its passage shows it), and
    without the page markers, running page numbers and letterheads its lines run across."""
    words, _ = _without_heading(body, provision)
    return "".join(line for line in words.splitlines(keepends=True) if not _page_furniture(line)).strip()


def list_depth(address: str | None) -> int:
    """How deep the marker of the passage's own provision sits in its lists: a paragraph's "(1)" and an article's
    item "1." at 0, a paragraph's item "a." at 1, an item's item at 2. An elucidation names what it explains
    ("Huruf a"), so it hangs nothing."""
    if not address or address.split("/")[0] == ELUCIDATION:
        return 0
    marked = [part for part in address.split("/") if _MARKED.match(part)]
    return max(len(marked) - 1, 0)


def utf16_offsets(text: str, offsets: Iterable[int]) -> dict[int, int]:
    """Each character offset, counted as an editor counts (CodeMirror, the browser): in UTF-16 units."""
    astral = [index for index, character in enumerate(text) if ord(character) > ASTRAL]
    return {offset: offset + bisect_left(astral, offset) for offset in offsets}


def _outside(read: list[Passage], piece: str) -> None:
    if piece.strip():
        read.append(Passage(None, piece, opens=False))


def _without_heading(piece: str, provision: Located) -> tuple[str, bool]:
    together = f"{provision.label} {provision.heading}" if provision.heading else None  # "BAB I KETENTUAN UMUM"
    names = {_name(name) for name in (provision.label, provision.heading, together) if name}
    lines = piece.splitlines(keepends=True)
    taken = set()  # heading lines; a page break between them ("BAB I", the next page, its title) is passed over
    for index, line in enumerate(lines):
        if _name(line) in names:
            taken.add(index)
        elif not _page_furniture(line):
            break
    if not taken and lines and not _hangs(provision.label):
        wording = _after_label(lines[0], provision.label)
        if wording is not None:
            return wording + "".join(lines[1:]), True
    return "".join(line for index, line in enumerate(lines) if index not in taken), bool(taken)


def _hangs(label: str) -> bool:
    """A paragraph's "(1)" and an item's "a." hang in their wording: they are its marker, not its heading."""
    return label.startswith("(") or bool(_ITEM_LABEL.match(label))


def _page_furniture(line: str) -> bool:
    """A blank line or what a page prints: kept in the text, but no end to its heading."""
    stripped = line.strip()
    return not stripped or stripped.isdigit() or is_page_furniture(stripped)


def _after_label(line: str, label: str) -> str | None:
    """The line's wording after the label that opens it ("Menimbang : a. bahwa …", "Pertama 1. Berdasarkan …")."""
    stripped = line.lstrip()
    if stripped[: len(label)].casefold() != label.casefold():
        return None
    rest = stripped[len(label) :]
    if not rest[:1].isspace() and not rest.startswith(":"):
        return None  # "Pasal 10" is not "Pasal 1" opening its wording
    wording = rest.lstrip().removeprefix(":").lstrip(" \t")
    return wording if wording.strip() else None


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
