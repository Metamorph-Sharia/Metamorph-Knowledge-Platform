"""A passage's wording laid out for reading: its printed lines joined into paragraphs and list items.

A text keeps the official file's lines, and read line for line a paragraph breaks wherever the page's line
did. Laid out, a passage is blocks:

    a paragraph   its lines joined by a space ("masing-" and "masing" by nothing)
    a list item   its number ("(1)", "a.", "16.", "A.", "IV.") hanging, and its wording; nested by the order
                  the kinds of number first appear: (1) › a. › 1. in an ayat, 1. › a. in a definitions article

A block ends at a blank line, before the next list item, and after a line that ends a sentence well short of
the passage's longest line (a paragraph's last line). A line in capitals (a title) and a heading line ("Huruf
a", "Ayat (2)") stand apart. Page furniture goes: a page marker becomes a page start in the block it falls in,
the catchword above it ("c. FPJPS .…", the next page's first words) is dropped, and so is what a page prints
atop its wording: its number, a letterhead in capitals (structure/text.py). Nothing else changes but whitespace:
the words, their order and their punctuation are the text's.

The rules don't rest on each line being a printed one: a line split a word at a time, or a number alone on its
line (texts extracted before metamorph_contract.printed_lines), joins up the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from metamorph_platform.domain.structure.text import is_page_furniture

_PAGE_MARKER = re.compile(r"^<!-- page (\d+) -->$")
_PRINTED_PAGE_NUMBER = re.compile(r"^\d{1,4}$")  # "3" just below a page marker; "- 3 -" is furniture already
_CATCHWORD = re.compile(r"\s*(?:(?:\.\s*){3}|…|\.…)$")
_ITEM = re.compile(r"^(\(\d{1,3}[a-z]?\)|\d{1,3}[a-z]?[.)]|[a-z][.)]|[IVXL]{1,6}\.|[A-Z][.)])(?:\s+|$)")
_ROMAN = re.compile(r"^[IVXL]+\.$")
_HEADING_LINE = re.compile(r"^(?:Huruf|Angka|Ayat|Pasal|Butir)\s+\S{1,6}$")
_SENTENCE_END = re.compile(r"[.:;?!]$")
SHORT_LINE = 0.75  # of the passage's longest line: a sentence ending on a line this short ends its paragraph
CAPITALS = 0.8  # of a line's letters in capitals: a title, not wording


@dataclass(frozen=True)
class Block:
    text: str  # its lines joined; a list item's number not included
    marker: str | None = None  # "(1)", "a.", "16.": a list item's number
    depth: int = 0  # a list item's nesting, from 0
    pages: tuple[tuple[int, int], ...] = ()  # (where in `text` a page of the official file starts, its number)


@dataclass
class _Open:
    marker: str | None
    depth: int
    text: str = ""
    pages: list[tuple[int, int]] = field(default_factory=list)
    waiting: list[int] = field(default_factory=list)  # pages starting before the block's next word

    def add(self, line: str) -> None:
        hyphenated = self.text.endswith("-") and line[:1].islower()
        start = len(self.text) + (1 if self.text and not hyphenated else 0)
        self.text = self.text + ("" if hyphenated or not self.text else " ") + line
        self.pages.extend((start, page) for page in self.waiting)
        self.waiting.clear()

    def block(self) -> Block:
        return Block(self.text, self.marker, self.depth, tuple(self.pages))


def layout(text: str) -> list[Block]:
    lines = _content(text)
    widest = max((len(line) for line in lines if isinstance(line, str)), default=0)
    blocks: list[Block] = []
    styles: list[str] = []  # the kinds of list number seen, outermost first
    current: _Open | None = None
    waiting: list[int] = []  # pages starting before the next block

    def close() -> None:
        nonlocal current
        if current is not None and (current.text or current.marker):  # a number without wording is still kept
            blocks.append(current.block())
        current = None

    for line in lines:
        numbered_only = current is not None and current.marker is not None and not current.text
        if line is None:  # a blank line, unless a number alone on its line waits for its wording
            if not numbered_only:
                close()
            continue
        if isinstance(line, int):  # a page starts
            (current.waiting if current is not None else waiting).append(line)
            continue
        item = _ITEM.match(line)
        apart = _in_capitals(line) or bool(_HEADING_LINE.match(line))
        if item or (apart and not numbered_only) or current is None:
            if current is not None and current.waiting:
                waiting = current.waiting + waiting
                current.waiting = []
            close()
            marker = item[1] if item else None
            current = _Open(marker, _depth(styles, marker) if marker else 0)
            current.waiting, waiting = waiting, []
            line = line[item.end() :] if item else line
        if line:
            current.add(line)
        if apart or (_SENTENCE_END.search(line) and len(line) < SHORT_LINE * widest):
            close()
    if current is not None:
        waiting = current.waiting + waiting
    close()
    if waiting and blocks:  # a page starting after the passage's last words: at the end of them
        last = blocks[-1]
        blocks[-1] = replace(last, pages=last.pages + tuple((len(last.text), page) for page in waiting))
    elif waiting:  # a passage that is only a page turn: kept, so the reader still shows where the page starts
        blocks.append(Block("", pages=tuple((0, page) for page in waiting)))
    return blocks


def _content(text: str) -> list[str | int | None]:
    """Each line that is wording (whitespace collapsed), a page's number where it starts, None for a blank line.
    The blank lines around a page break are the page's, not the text's, and the furniture is dropped."""
    raw = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str | int | None] = []
    for index, line in enumerate(raw):
        page = _PAGE_MARKER.match(line)
        if page:
            while out and out[-1] is None:
                out.pop()
            if out and isinstance(out[-1], str) and _is_catchword(out[-1], raw[index + 1 :]):
                out.pop()
            out.append(int(page[1]))
        elif not line:
            if out and not isinstance(out[-1], int) and out[-1] is not None:
                out.append(None)
        elif (out and isinstance(out[-1], int) and _furniture(line)) or _is_catchword(line, raw[index + 1 :]):
            continue  # what a page prints atop its wording; a page's catchword, where no page break is marked
        else:
            out.append(line)
    return out


def _is_catchword(line: str, following: list[str]) -> bool:
    """The next page's first words printed at this one's foot, ending in dots: "c. FPJPS .…"."""
    found = _CATCHWORD.search(line)
    if not found:
        return False
    words = line[: found.start()].strip()
    first = next((each for each in following if each and not _PAGE_MARKER.match(each) and not _furniture(each)), "")
    return bool(words) and first.startswith(words)


def _furniture(line: str) -> bool:
    """Atop a page: its number ("3", "- 3 -") or a letterhead in capitals ("PRESIDEN / REPUBLIK INDONESIA"). Not
    elsewhere: "Republik Indonesia." ending a sentence reads like a letterhead to structure/text.py."""
    return bool(_PRINTED_PAGE_NUMBER.match(line)) or (is_page_furniture(line) and not _has_lowercase(line))


def _has_lowercase(line: str) -> bool:
    return any(char.islower() for char in line)


def _depth(styles: list[str], marker: str) -> int:
    style = _style(marker)
    if style in styles:
        del styles[styles.index(style) + 1 :]
    else:
        styles.append(style)
    return styles.index(style)


def _style(marker: str) -> str:
    """The kind of number: "(12)" and "(3a)" → "(1)", "b." → "a.", "B." → "A.", "IV." → "I.", "16a." → "1."."""
    if _ROMAN.match(marker):
        return "I."
    return re.sub(r"[A-Z]", "A", re.sub(r"[a-z]", "a", re.sub(r"\d+[a-z]?", "1", marker)))


def _in_capitals(line: str) -> bool:
    letters = [char for char in line if char.isalpha()]
    return len(letters) > 1 and sum(char.isupper() for char in letters) / len(letters) >= CAPITALS
