"""Page furniture taken off a document's pages, each removal logged; the wording itself is never changed.

The rules run in order:

    generated    on a page read from its image, a block the vision model wrote instead of reading: an English
                 description of a picture ("The chart displays …", "The image contains no discernible text …")
    furniture    blocks the reader marked as a header, footer, page number or side note
    serial       the State Secretariat's print serial, "SK No 054949 C" (and OCR's "SK No l19tt6l C")
    repeated     lines at the top or foot of the page that recur on many pages: a running head ("PRESIDEN
                 REPUBLIK INDONESIA", misread or not; its first place stays), a printed page number ("-3-")
    catchword    a page's last line repeating the start of the next page ("33. Penerbitan .")

then each block is tidied: a word hyphenated across two lines is joined, spaces are collapsed, empty lines and
blocks go. A line that opens with a structure word or an item marker ("Pasal 12", "(1)") is never furniture,
and neither is the first page's head, which names the issuer.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from metamorph_pdf_text.domain.page import MARKED_FURNITURE, Block, Page
from metamorph_pdf_text.domain.patterns import shows_structure

GENERATED, FURNITURE, SERIAL, REPEATED, CATCHWORD = "generated", "furniture", "serial", "repeated", "catchword"

BAND = 0.12  # of the page's height: the top and foot where running heads, page numbers and serials sit
EDGE_LINES = 3  # of a block in a band, how many of its first (top) or last (foot) lines can be furniture
RECURRING_SHARE = 0.3  # of a document's pages a band line must appear on to be furniture
RECURRING_PAGES = 3  # and at least this many, so a short document keeps its lines
OPENING_LINES = 6  # of the next page, where the wording a catchword repeats begins
SAME_LINE = 0.85  # similarity of two band lines that are one line read differently ("INDONESIA", "INDONESTA")

_SERIAL = re.compile(r"^SK\s*N[o0](?![a-z])\.?\s*(.{3,14}?)\s*[.:]?$")  # not "SK Nomor …"
_SERIAL_TOKENS = 3  # "SK No 054949 C", "SK No I l29l2c": the serial, misread, is a few short tokens
_SERIAL_WORD = 4  # letters of a word the serial never holds ("SK No 12 Tahun 2020" is a decree)
_PRINTED_PAGE_NUMBER = re.compile(
    r"^[-–—\s]*(?:hal(?:aman)?\.?\s*)?(\d{1,4})(?:\s*(?:dari|/)\s*\d{1,4})?[-–—\s]*$", re.IGNORECASE
)
_CATCHWORD_END = re.compile(r"(?:\s\.|\.{2,}|(?:\.\s+){2,}\.?|…)$")
_SENTENCE_END = re.compile(r"[.;:,]$")
_WORD = re.compile(r"\w+")
_LETTERS = re.compile(r"[a-z]+")
# Function words: English ones make most of an English sentence's words, and an Indonesian one's never do
_ENGLISH = frozenset(
    {"the", "a", "an", "is", "are", "of", "and", "or", "with", "to", "in", "on", "it", "its", "this", "that"}
    | {"there", "no", "as", "by", "be", "for"}
)
_INDONESIAN = frozenset(
    {"yang", "dan", "di", "dalam", "dengan", "untuk", "pada", "atau", "dari", "ini", "itu", "adalah", "tidak"}
    | {"oleh", "ke", "tersebut"}
)
_GENERATED_WORDS = 8  # at least, in a sentence told apart by its function words
_ENGLISH_SHARE = 0.2  # of its words, at least
_INDONESIAN_SHARE = 0.05  # of its words, under
_HYPHENATED = re.compile(r"(\w+)-$")


@dataclass(frozen=True)
class Removal:
    rule: str
    page: int
    text: str


@dataclass(frozen=True)
class Cleaned:
    pages: tuple[Page, ...]
    removals: tuple[Removal, ...]


def clean(pages: Sequence[Page], from_images: Collection[int] = ()) -> Cleaned:
    """`from_images`: the numbers of the pages a reader read from their images, where it may have written text."""
    log: list[Removal] = []
    kept = [_without_generated(page, log) if page.number in from_images else page for page in pages]
    kept = [_without_marked_furniture(page, log) for page in kept]
    kept = [_without_lines(page, _is_serial, SERIAL, log) for page in kept]
    kept = _without_recurring_band_lines(kept, log)
    kept = _without_catchwords(kept, log)
    return Cleaned(tuple(_tidied(page) for page in kept), tuple(log))


def _without_generated(page: Page, log: list[Removal]) -> Page:
    kept = []
    for block in page.blocks:
        if _is_generated(block.text):
            log.append(Removal(GENERATED, page.number, block.text))
        else:
            kept.append(block)
    return page.with_blocks(kept)


def _is_generated(text: str) -> bool:
    words = _LETTERS.findall(text.lower())
    if len(words) < _GENERATED_WORDS:
        return False
    english = sum(word in _ENGLISH for word in words) / len(words)
    indonesian = sum(word in _INDONESIAN for word in words) / len(words)
    return english >= _ENGLISH_SHARE and indonesian < _INDONESIAN_SHARE


def _without_marked_furniture(page: Page, log: list[Removal]) -> Page:
    kept = []
    for block in page.blocks:
        if block.kind in MARKED_FURNITURE and not _is_kept_furniture(page, block):
            log.append(Removal(FURNITURE, page.number, block.text))
        else:
            kept.append(block)
    return page.with_blocks(kept)


def _is_kept_furniture(page: Page, block: Block) -> bool:
    return _is_first_page_head(page, block) or any(shows_structure(line.strip()) for line in block.lines)


def _is_first_page_head(page: Page, block: Block) -> bool:
    return page.number == 1 and _in_top_band(page, block)


def _is_serial(line: str) -> bool:
    """The print serial as printed or as OCR misread it: "SK No 054949 C", "SK No l19tt6l C", "SK No LIS5611A"."""
    match = _SERIAL.match(line.strip())
    if not match:
        return False
    tokens = match[1].split()
    return (
        len(tokens) <= _SERIAL_TOKENS
        and any(character.isdigit() for character in match[1])
        and all(
            token.replace("-", "").isalnum() and not (token.isalpha() and len(token) >= _SERIAL_WORD)
            for token in tokens
        )
    )


def _without_lines(page: Page, unwanted: Callable[[str], bool], rule: str, log: list[Removal]) -> Page:
    blocks = []
    for block in page.blocks:
        kept = []
        for line in block.lines:
            if unwanted(line):
                log.append(Removal(rule, page.number, line))
            else:
                kept.append(line)
        if kept:
            blocks.append(block.with_lines(kept))
    return page.with_blocks(blocks)


# Repeated band lines

Place = tuple[int, int, int]  # a line's page number, block index and line index


def _without_recurring_band_lines(pages: list[Page], log: list[Removal]) -> list[Page]:
    recurring = _Recurring(pages)
    return [_without_recurring(page, recurring, log) for page in pages]


class _Recurring:
    """The band lines that recur through a document. A printed page number recurs when it follows the pages: a
    number a page at the document's offset from the page's own ("3" on its third page, or on its fourth when the
    cover is unnumbered); a row number or code in a table doesn't. Any other line recurs when it is on enough pages,
    however each misreads it ("PRES I DEN", "PRESIDEN"); its first place stays, as it may open what then recurs
    (a table's head, an annex's title)."""

    def __init__(self, pages: Sequence[Page]) -> None:
        self._groups = _LineGroups()
        places: dict[int, list[Place]] = {}
        offsets: Counter[int] = Counter()  # offset of the printed page number → pages printing it
        for page in pages:
            page_offsets = set()
            for block_index, line_index, line in _edge_lines(page):
                number = _printed_page_number(line)
                if number is not None:
                    page_offsets.add(number - page.number)
                else:
                    places.setdefault(self._groups.of(line), []).append((page.number, block_index, line_index))
            offsets.update(page_offsets)
        needed = max(RECURRING_PAGES, math.ceil(RECURRING_SHARE * len(pages)))
        self._offset = next((offset for offset, count in offsets.most_common(1) if count >= needed), None)
        self._first = {
            group: found[0] for group, found in places.items() if len({number for number, _, _ in found}) >= needed
        }

    def is_furniture(self, page: Page, block_index: int, line_index: int, line: str) -> bool:
        number = _printed_page_number(line)
        if number is not None:
            return self._offset is not None and number - page.number == self._offset
        group = self._groups.of(line)
        return group in self._first and self._first[group] != (page.number, block_index, line_index)


def _edge_lines(page: Page) -> Iterator[tuple[int, int, str]]:
    """The lines at a band block's edge that could be furniture: its first lines at the top, its last at the foot."""
    for block_index, block in enumerate(page.blocks):
        for line_index in _edge_indices(page, block):
            line = block.lines[line_index]
            if _looks_like_furniture(line):
                yield block_index, line_index, line


def _edge_indices(page: Page, block: Block) -> list[int]:
    count = len(block.lines)
    indices = set()
    if _in_top_band(page, block):
        indices.update(range(min(EDGE_LINES, count)))
    if _in_foot_band(page, block):
        indices.update(range(max(0, count - EDGE_LINES), count))
    return sorted(indices)


def _without_recurring(page: Page, recurring: _Recurring, log: list[Removal]) -> Page:
    """Each band block's leading (top) or trailing (foot) run of recurring lines taken off; the first page's head
    is kept whole."""
    blocks = []
    for block_index, block in enumerate(page.blocks):
        lines = block.lines
        start, end = (0, len(lines)) if _is_first_page_head(page, block) else _kept(page, block_index, recurring)
        log.extend(Removal(REPEATED, page.number, line) for line in lines[:start] + lines[end:])
        if start < end:
            blocks.append(block.with_lines(lines[start:end]))
    return page.with_blocks(blocks)


def _kept(page: Page, block_index: int, recurring: _Recurring) -> tuple[int, int]:
    """The block's lines kept, as a range: those before `start` and from `end` on recur."""
    block = page.blocks[block_index]
    lines = block.lines

    def furniture(index: int) -> bool:
        return _looks_like_furniture(lines[index]) and recurring.is_furniture(page, block_index, index, lines[index])

    start, end = 0, len(lines)
    if _in_top_band(page, block):
        while start < min(end, EDGE_LINES) and furniture(start):
            start += 1
    if _in_foot_band(page, block):
        while end > max(start, len(lines) - EDGE_LINES) and furniture(end - 1):
            end -= 1
    return start, end


def _looks_like_furniture(line: str) -> bool:
    """A line that could be a running head or page number: not wording (a sentence, a heading, an item)."""
    stripped = line.strip()
    return bool(_key(stripped)) and not shows_structure(stripped) and not _SENTENCE_END.search(stripped)


def _printed_page_number(line: str) -> int | None:
    match = _PRINTED_PAGE_NUMBER.match(line.strip())
    return int(match[1]) if match else None


class _LineGroups:
    """Band lines grouped as one when they are one line read differently: "PRES I DEN" and "PRESIDEN",
    "SEOJK Nomor: 5/SEOJK.03/2025" on each page of its annex (a number is its digits' place, not its value)."""

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._group_of: dict[str, int] = {}

    def of(self, line: str) -> int:
        key = _key(line)
        if key not in self._group_of:
            self._group_of[key] = self._similar(key)
        return self._group_of[key]

    def _similar(self, key: str) -> int:
        """The group of the first line seen that this one is alike, or a new group."""
        for index, known in enumerate(self._keys):
            if _alike(key, known):
                return index
        self._keys.append(key)
        return len(self._keys) - 1


def _key(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"[^\w]|_", "", line.casefold()))


def _alike(key: str, known: str) -> bool:
    return key == known or (len(key) > 3 and SequenceMatcher(None, key, known).ratio() >= SAME_LINE)


def _in_top_band(page: Page, block: Block) -> bool:
    return block.bbox.y0 < BAND * page.height


def _in_foot_band(page: Page, block: Block) -> bool:
    return block.bbox.y1 > (1 - BAND) * page.height


# Catchwords


def _without_catchwords(pages: list[Page], log: list[Removal]) -> list[Page]:
    kept = []
    for page, following in zip(pages, [*pages[1:], None], strict=True):
        if following is not None and page.blocks and _is_catchword(page.blocks[-1].lines[-1], following):
            *blocks, last = page.blocks
            log.append(Removal(CATCHWORD, page.number, last.lines[-1]))
            if len(last.lines) > 1:
                blocks.append(last.with_lines(last.lines[:-1]))
            page = page.with_blocks(blocks)
        kept.append(page)
    return kept


def _is_catchword(line: str, following: Page) -> bool:
    """The line ends as a catchword does ("…", " .") and one of the next page's first lines opens with its words.
    One of the first lines, not the first: the next page may open with a running head kept as too rare to go."""
    stripped = line.strip()
    if not _CATCHWORD_END.search(stripped):
        return False
    words = _words(_CATCHWORD_END.sub("", stripped))
    opening = [text for block in following.blocks for text in block.lines][:OPENING_LINES]
    starts = (_words(" ".join(opening[index:]))[: len(words)] for index in range(len(opening)))
    return bool(words) and words in starts


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


# Tidying


def _tidied(page: Page) -> Page:
    blocks = []
    for block in page.blocks:
        lines = [line for line in (_spaced(line) for line in _dehyphenated(block.lines)) if line]
        if lines:
            blocks.append(block.with_lines(lines))
    return page.with_blocks(blocks)


def _dehyphenated(lines: list[str]) -> list[str]:
    """A word split across two lines ("perusa-" / "haan") joined. A repeated word keeps its hyphen
    ("badan-" / "badan", "Undang-" / "Undang"); before a capital that isn't one, the lines stay apart."""
    joined: list[str] = []
    for line in lines:
        previous = joined[-1].rstrip() if joined else ""
        hyphenated = _HYPHENATED.search(previous)
        following = line.lstrip()
        if hyphenated and _first_word(following).casefold() == hyphenated[1].casefold():
            joined[-1] = previous + following
        elif hyphenated and following[:1].islower():
            joined[-1] = previous[:-1] + following
        else:
            joined.append(line)
    return joined


def _first_word(text: str) -> str:
    match = _WORD.match(text)
    return match[0] if match else ""


def _spaced(line: str) -> str:
    return re.sub(r" {2,}", " ", line).strip()
