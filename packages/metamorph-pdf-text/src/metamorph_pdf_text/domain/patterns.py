"""How a line shows the structure of an Indonesian legal text: what cleaning must never remove, and what the
renderer puts on a line of its own."""

from __future__ import annotations

import re

_ORDINALS = "Pertama|Kedua|Ketiga|Keempat|Kelima|Keenam|Ketujuh|Kedelapan|Kesembilan|Kesepuluh"

# A heading alone on its line: "BAB IV", "Bagian Kesatu", "Paragraf 2", "Pasal 5", "Pasal 7A", "Pasal I",
# an opening label ("Menimbang :", "MEMUTUSKAN:"), a fatwa's ruling ("Kedua :").
HEADING_LINE = re.compile(
    r"^(?:BAB\s+[IVXLC]+|Bagian\s+Ke\w+|Paragraf\s+\d+|Pasal\s+(?:\d+[A-Z]?|[IVXLC]+)\.?"
    r"|(?:Menimbang|Mengingat|Memperhatikan|Menetapkan|Memutuskan|MEMUTUSKAN)\s*:?"
    rf"|(?:{_ORDINALS})\s*:?)$"
)

# A line that opens with a structure word: never furniture, even when a reader marks it so.
STRUCTURE_START = re.compile(r"^(?:BAB|Bagian|Paragraf|Pasal|Ayat|Huruf|Angka|Lampiran)\b", re.IGNORECASE)

# A list item's marker opening its line: "(1)", "1.", "1)", "a.", "a)", "IV." (not "1.000", which runs on).
ITEM_MARKER = re.compile(r"^(?:\(\d{1,3}[a-z]?\)|\d{1,3}[a-z]?[.)]|[a-z][.)]|[IVXLC]{1,6}\.)(?=\s|$)")


def shows_structure(line: str) -> bool:
    """A line cleaning never removes, however a reader marked it: a heading, an opening label, an item."""
    return bool(STRUCTURE_START.match(line) or ITEM_MARKER.match(line) or HEADING_LINE.match(line))
