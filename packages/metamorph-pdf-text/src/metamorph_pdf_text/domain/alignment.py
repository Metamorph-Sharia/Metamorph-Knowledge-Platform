"""Whether two readings of a page hold the same words: the check that a layout reader kept a born-digital page's
wording, word for word, while it was free to change the order (two columns read one after the other).

Words are compared as the PDF spells them, case included; spacing and punctuation between them don't count.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"\w+")
# "masing-masing", and broken at its hyphen: "perundang-\nundangan"
_HYPHENATED_WORD = re.compile(r"\b(\w+)-\s*(\w+)\b")


@dataclass(frozen=True)
class Alignment:
    missing: Counter[str]  # in the reference, not the candidate
    added: Counter[str]  # in the candidate, not the reference

    @property
    def keeps_wording(self) -> bool:
        return not self.missing and not self.added


def aligned(candidate: str, reference: str) -> Alignment:
    found, expected = words(candidate), words(reference)
    return Alignment(missing=expected - found, added=found - expected)


def words(text: str) -> Counter[str]:
    """The words of `text`, as an alignment counts them."""
    return Counter(_WORD.findall(text))


def respelled(candidate: str, reference: str) -> str:
    """`candidate` with each word it joined at a hyphen spelled as `reference` has it: a reader that runs a
    paragraph's lines together drops the hyphen a line ended with ("perundangundangan", "masingmasing"). Only a
    joined word `reference` doesn't hold itself is respelled."""
    held = words(reference)
    spellings = {
        match[1] + match[2]: f"{match[1]}-{match[2]}"
        for match in _HYPHENATED_WORD.finditer(reference)
        if match[1] + match[2] not in held
    }
    return _WORD.sub(lambda word: spellings.get(word[0], word[0]), candidate) if spellings else candidate
