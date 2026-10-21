"""The lettered and numbered items of a provision ("a. bahwa …", "1. Bank adalah …", "a) …"), each a provision of
its own, so a curator, a citation or a retrieval can point at one:

    pasal-1/angka-3            a Ketentuan Umum's third definition
    pasal-5/ayat-1/huruf-a     a paragraph's first lettered item
    pasal-1/angka-3/huruf-b    an item within an item
    menimbang/huruf-a, mengingat/angka-2, romawi-ii/angka-3, diktum-kedua/angka-1

An item belongs to the innermost provision that holds wording: an article, a paragraph, a part of the preamble, a
circular's section or a fatwa's ruling. How deep it sits comes from the order its marker style appears in, as on
the printed page: the first style is the outer list, a new one nests in the item before it, and a style seen
before closes what nested after it. A list starts at "a" or "1" (an amendment may quote one from the item it
changes) and runs in order, so a reference wrapped onto its own line ("… dimaksud pada huruf / b. …") or a stray
number opens nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from metamorph_platform.domain.structure.builder import TreeBuilder
from metamorph_platform.domain.structure.text import CATCHWORD, Line

ITEM = 7  # the builder's level of an outer item; one nested in it is a level deeper
MAX_DEPTH = 3  # "1." › "a." › "1)": deeper is a table or a form, not a list
MAX_ITEM_JUMP = 2  # a page break or OCR loses the odd item; a letter further ahead is a reference
HOLDERS = frozenset({"pasal", "ayat", "menimbang", "mengingat", "memperhatikan", "romawi", "diktum"})

_MARKER = re.compile(r"^(?:([a-z])|(\d{1,3}))([.)])(?=\s)")  # "a. ", "1) ": not "1.000" nor "a.n."
_WRAPPED_REFERENCE = re.compile(r"\b(?:huruf|angka|ayat|pasal)$", re.IGNORECASE)  # "… dimaksud pada huruf" / "b. …"


@dataclass
class _List:
    style: tuple[str, str]  # its kind and its marker's punctuation: ("huruf", "."), ("angka", ")")
    last: int  # the last item's value: a = 1
    address: str  # the last item's


class Items:
    def __init__(self, builder: TreeBuilder) -> None:
        self.b = builder
        self._holder: str | None = None
        self._lists: list[_List] = []  # the lists open in the holder, outer first

    def feed(self, line: Line, *, previous: str, quoted: bool = False) -> bool:
        """True when `line` opens an item. `quoted`: the line is in what an amendment quotes."""
        holder = self.b.holder(below=ITEM)
        found = _MARKER.match(line.text)
        if (
            not found
            or holder is None
            or holder.kind not in HOLDERS
            or CATCHWORD.search(line.text)
            or _WRAPPED_REFERENCE.search(previous)
        ):
            return False
        if holder.address != self._holder:
            self._holder, self._lists = holder.address, []
        letter, number, punctuation = found.groups()
        kind, name = ("huruf", letter) if letter else ("angka", number)
        style, value = (kind, punctuation), ord(letter) - ord("a") + 1 if letter else int(number)
        depth = self._depth(style, value, quoted)
        if depth is None:
            return False
        parent = holder.address if depth == 0 else self._lists[depth - 1].address
        address = f"{parent}/{kind}-{name}"
        if not self.b.open(ITEM + depth, address, kind, f"{name}{punctuation}", line):
            return False
        self._lists[depth:] = [_List(style, value, address)]
        return True

    def _depth(self, style: tuple[str, str], value: int, quoted: bool) -> int | None:
        """The depth of the list the item continues, or of the one it starts; None when it does neither."""
        for depth, open_list in enumerate(self._lists):
            if open_list.style == style:
                return depth if open_list.last < value <= open_list.last + MAX_ITEM_JUMP else None
        if len(self._lists) >= MAX_DEPTH or not (value == 1 or quoted):
            return None
        return len(self._lists)
