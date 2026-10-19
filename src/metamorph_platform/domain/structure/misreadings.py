"""What a heading damaged by OCR may have said: every reading, most literal first.

OCR of a scanned law loses spaces and confuses glyphs, so one damaged heading has several readings:
"Pasa136" is Pasal 136 with the l dropped, or Pasal 36 with the l read as 1. Only the sequence can
tell, so these functions list the readings and the grammar keeps the one that continues it.
"""

from __future__ import annotations

import re

# An inserted article is lettered A, B, C … ("Pasal 82A"); an O after the digits is a misread 0 ("Pasal 1O").
_INSERTED = r"[A-NP-Z]?"
_ARTICLE = re.compile(rf"^(?:Pasal|PASAL)\s*(\d+{_INSERTED})$")  # "Pasal12" too: only the space was lost
_ROMAN_ARTICLE = re.compile(r"^(?:Pasal|PASAL)\s+([IVXLC]+)$")
_L_READ_AS_DIGIT = re.compile(rf"^Pasa([17Il|i])\s*(\d+{_INSERTED})$")  # "Pasa136", "Pasa722", "PasaI 5"
_L_DROPPED = re.compile(rf"^Pasa\s*(\d+{_INSERTED})$")  # "Pasa12"
_CONFUSED_NUMBER = re.compile(r"^(?:Pasal|PASAL)\s+([\dOoIl][\dOoIl ]{0,5})$")  # "Pasal 1O", "Pasal 2 I", "Pasal 1 1"
_PARAGRAPH = re.compile(r"^[(\[{]\s*([\dOoIl]{1,2})\s*([)\]}])?(?=\s|$)")  # "(I)", "{2)", "( 1)", "(21"
# "l2l": both brackets read as l. A closing one is required: "l9 ayat (1)" is a misread number, not a paragraph.
_PARAGRAPH_IN_LS = re.compile(r"^l(\d{1,2})[l)](?=\s|$)")
_ONE = {"I", "l"}  # a paragraph marker's lone I or l: "(I)", "(l)"
_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})  # not S or B: Pasal 184S is a real article


def article_numbers(text: str) -> list[str]:
    """The numbers an article heading line may carry; empty when it isn't one."""
    if found := _ARTICLE.match(text) or _ROMAN_ARTICLE.match(text):
        return [found[1]]
    if found := _L_READ_AS_DIGIT.match(text):
        dropped = [found[1] + found[2]] if found[1] in "17" else []  # "Pasa136" may be Pasal 136 after all
        return [*dropped, found[2]]
    if found := _L_DROPPED.match(text):
        return [found[1]]
    if (found := _CONFUSED_NUMBER.match(text)) and (number := _digits(found[1])):
        return [number]
    return []


def paragraph_numbers(text: str) -> list[int]:
    """The numbers a damaged paragraph marker at the start of a line may carry: "(21 X" is (2) or (21),
    since OCR also reads the closing bracket as 1."""
    if found := _PARAGRAPH_IN_LS.match(text):
        return [int(found[1])]
    found = _PARAGRAPH.match(text)
    if found and found[1] in _ONE:
        return [1]
    if not found or not (number := _digits(found[1])):
        return []
    if not found[2] and len(found[1]) == 2 and found[1][-1] in "1l":
        return [int(number), int(number[0])]
    return [int(number)]


def _digits(raw: str) -> str | None:
    """ "1O" → "10", "2 I" → "21", "lO" → "10"; None unless every glyph reads as a digit, and one already was
    or one can't be a Roman numeral ("II" stays Pasal II)."""
    if not re.search(r"[\dOol]", raw):
        return None
    number = raw.translate(_DIGITS).replace(" ", "")
    return str(int(number)) if number.isdigit() else None
