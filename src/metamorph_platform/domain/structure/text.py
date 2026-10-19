"""Reading a stored text line by line, without changing it: offsets always point into the original."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher

_PAGE_MARKER = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)
_RUNNING_PAGE_NUMBER = re.compile(r"^-\s*(?=[\dIlOt|]*\d)[\dIlOt|]+\s*-$")  # "- 5 -" atop a page; OCR: "-2t2-"
# A presidential instrument's letterhead, atop every page: "PRESIDEN / REPUBLIK INDONESIA", OCR'd "PRES !DEN",
# "REPUBL|K". Only as a line of its own: "PRESIDEN REPUBLIK INDONESIA," above a signature is content.
_LETTERHEAD = ("PRESIDEN", "REPUBLIKINDONESIA", "PRESIDENREPUBLIKINDONESIA")
_LETTERHEAD_SIMILARITY = 0.8
_LONGEST_LETTERHEAD_LINE = 40
_ROMAN = re.compile(r"^[IVXLC]+$", re.IGNORECASE)
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


@dataclass(frozen=True)
class Line:
    start: int
    end: int  # just past its newline
    text: str  # stripped


def lines(text: str) -> Iterator[Line]:
    """Every line that carries content: not blank, not page furniture (a page marker, a running page number,
    a letterhead)."""
    offset = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if _carries_content(stripped):
            yield Line(offset, offset + len(raw), stripped)
        offset += len(raw)


def next_line(text: str, offset: int) -> str:
    """The first content line starting at or after `offset` (a line's start), stripped; "" at the end."""
    while offset < len(text):
        end = text.find("\n", offset)
        end = len(text) if end < 0 else end + 1
        if _carries_content(stripped := text[offset:end].strip()):
            return stripped
        offset = end
    return ""


def _carries_content(stripped: str) -> bool:
    return (
        bool(stripped)
        and not _PAGE_MARKER.match(stripped)
        and not _RUNNING_PAGE_NUMBER.match(stripped)
        and not _is_letterhead(stripped)
    )


def _is_letterhead(stripped: str) -> bool:
    if len(stripped) > _LONGEST_LETTERHEAD_LINE or stripped.endswith(",") or not stripped[0].isupper():
        return False
    letters = re.sub(r"[^A-Z]", "", stripped.upper())
    return any(SequenceMatcher(None, letters, form).ratio() >= _LETTERHEAD_SIMILARITY for form in _LETTERHEAD)


class Pages:
    """Which page a character offset falls on, from the text's `<!-- page N -->` markers (None if unpaged)."""

    def __init__(self, text: str) -> None:
        markers = [(match.start(), int(match[1])) for match in _PAGE_MARKER.finditer(text)]
        self._starts = [start for start, _ in markers]
        self._numbers = [number for _, number in markers]

    def at(self, offset: int) -> int | None:
        index = bisect.bisect_right(self._starts, offset) - 1
        return self._numbers[index] if index >= 0 else None


def is_roman(value: str) -> bool:
    return bool(_ROMAN.match(value))


def roman_value(numeral: str) -> int:
    values = [_ROMAN_VALUES[char] for char in numeral.lower()]
    return sum(-v if v < following else v for v, following in zip(values, [*values[1:], 0], strict=True))
