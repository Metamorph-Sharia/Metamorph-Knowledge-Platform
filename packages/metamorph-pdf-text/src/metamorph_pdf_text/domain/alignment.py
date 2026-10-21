"""Whether two readings of a page hold the same words: the check that a layout reader kept a born-digital page's
wording, word for word, while it was free to change the order (two columns read one after the other).

Words are compared as the PDF spells them, case included; spacing and punctuation between them don't count.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"\w+")


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
