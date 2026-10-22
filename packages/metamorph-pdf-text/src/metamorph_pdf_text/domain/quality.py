"""How noisy a page's text is, measured on the text itself and not on how it was made: a "text layer" can be the
publisher's own poor OCR. The measures are those of the 2026-10-16 and 2026-10-20 studies (Metamorph-EDA).

    unknown_word_rate        words of 3+ letters missing from a vocabulary of clean texts
    confusions_per_thousand  tokens with an OCR character confusion: a digit inside a word ("REPUBL1K"), a letter
                             inside a number ("1O"), a stray glyph inside a word ("BERUS!A")
    damaged_headings         "Pasal" headings OCR broke ("Pasa1 5", "Pasal 1O", "P a s a l 3")
    junk_rate                characters no Indonesian text holds: CJK, kana, Greek, private use ("動物乃らθ")
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

NOISY_UNKNOWN_WORDS = 0.08
NOISY_CONFUSIONS = 10.0
NOISY_DAMAGED_HEADINGS = 2
NOISY_JUNK = 0.01

_WORD = re.compile(r"[A-Za-z]{3,}")
_TOKEN = re.compile(r"\S+")
_DIGIT_IN_WORD = re.compile(r"^(?=.*[A-Za-z]{2})(?=.*\d)[A-Za-z]*\d+[A-Za-z]+[A-Za-z\d]*$")
_LETTER_IN_NUMBER = re.compile(r"^\d+[OoIlSB]\d*$|^[OoIl]\d+$")
_STRAY_GLYPH = re.compile(r"[A-Za-z][{}|!\\~^][A-Za-z]")
_DAMAGED_HEADING = re.compile(
    r"(?m)^\s*(?:"
    r"Pasa[1I|i]\s*\d+"  # Pasa1 5, PasaI 5
    r"|P\s?a\s?s\s?a\s?l\s+\d+\s+[\dIlO]\b"  # Pasal 2 I, Pasal 1 1
    r"|Pasal\s+(?:\d+[OIlSB]\d+|[OIlSB]\d+|\d+[Ol])"  # Pasal 1O0, Pasal I5, Pasal 2O; not "Pasal II", "Pasal 7B"
    r"|P\s+a\s+s\s+a\s+l\s+\d+"  # letter-spaced
    r")\s*$"
)
_JUNK = re.compile(r"[Ͱ-Ͽ぀-ヿ㐀-䶿一-鿿豈-﫿-]")


@dataclass(frozen=True)
class PageQuality:
    characters: int
    unknown_word_rate: float
    confusions_per_thousand: float
    damaged_headings: int
    junk_rate: float

    @property
    def is_noisy(self) -> bool:
        return (
            self.unknown_word_rate > NOISY_UNKNOWN_WORDS
            or self.confusions_per_thousand > NOISY_CONFUSIONS
            or self.damaged_headings > NOISY_DAMAGED_HEADINGS
            or self.junk_rate > NOISY_JUNK
        )


def page_quality(text: str, vocabulary: Collection[str]) -> PageQuality:
    """`vocabulary`: the lowercased words of clean texts."""
    words = [word.lower() for word in _WORD.findall(text)]
    tokens = _TOKEN.findall(text)
    characters = sum(not character.isspace() for character in text)
    return PageQuality(
        characters=characters,
        unknown_word_rate=_share(sum(word not in vocabulary for word in words), len(words)),
        confusions_per_thousand=1000 * _share(sum(_is_confusion(token) for token in tokens), len(tokens)),
        damaged_headings=len(_DAMAGED_HEADING.findall(text)),
        junk_rate=_share(len(_JUNK.findall(text)), characters),
    )


def _is_confusion(token: str) -> bool:
    return bool(_DIGIT_IN_WORD.match(token) or _LETTER_IN_NUMBER.match(token) or _STRAY_GLYPH.search(token))


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0
