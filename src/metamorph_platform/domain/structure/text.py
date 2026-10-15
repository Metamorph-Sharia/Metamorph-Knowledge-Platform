"""Reading a stored text line by line, without changing it: offsets always point into the original."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from dataclasses import dataclass

_PAGE_MARKER = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)
_RUNNING_PAGE_NUMBER = re.compile(r"^-\s*\d+\s*-$")  # "- 5 -" printed at the top of a page
_ROMAN = re.compile(r"^[IVXLC]+$", re.IGNORECASE)
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


@dataclass(frozen=True)
class Line:
    start: int
    end: int  # just past its newline
    text: str  # stripped


def lines(text: str) -> Iterator[Line]:
    """Every line that carries content: not blank, not a page marker, not a running page number."""
    offset = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped and not _PAGE_MARKER.match(stripped) and not _RUNNING_PAGE_NUMBER.match(stripped):
            yield Line(offset, offset + len(raw), stripped)
        offset += len(raw)


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
