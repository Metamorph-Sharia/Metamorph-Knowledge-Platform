"""The dates a document states about itself, for sources that send none (OJK's and BI's records carry no dates).

    Ditetapkan di Jakarta pada tanggal 26 Februari 2019     → enacted
    Diundangkan di Jakarta pada tanggal 27 Februari 2019    → promulgated
    … mulai berlaku pada tanggal diundangkan                 → effective = promulgated (or ditetapkan, or a date)

The last "mulai berlaku" before the elucidation is the closing article's: earlier ones are transitional
rules for some provisions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = ("januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus", "september", "oktober",
          "november", "desember")  # fmt: skip
SIGNATURE_WINDOW = 150  # characters after "Ditetapkan di" in which its date appears

_DATE = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(MONTHS)})\s+(\d{{4}})\b", re.IGNORECASE)
_ENACTED = re.compile(r"\b(?:Ditetapkan|Disahkan)\s+di\b", re.IGNORECASE)
_PROMULGATED = re.compile(r"\bDiundangkan\s+di\b", re.IGNORECASE)
_IN_FORCE = re.compile(
    rf"mulai\s+berlaku\s+(?:sejak|pada)\s+tanggal\s+(?:(?P<on>diundangkan|ditetapkan)|(?P<date>{_DATE.pattern}))",
    re.IGNORECASE,
)
_ELUCIDATION = re.compile(r"^\s*PENJELASAN\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TextDates:
    enacted: date | None = None
    promulgated: date | None = None
    effective: date | None = None


def text_dates(text: str) -> TextDates:
    elucidation = _ELUCIDATION.search(text)
    body = text[: elucidation.start()] if elucidation else text
    enacted, promulgated = _signed(body, _ENACTED), _signed(body, _PROMULGATED)
    return TextDates(enacted=enacted, promulgated=promulgated, effective=_effective(body, enacted, promulgated))


def _signed(text: str, marker: re.Pattern[str]) -> date | None:
    for found in reversed(list(marker.finditer(text))):
        day = _first_date(text[found.end() : found.end() + SIGNATURE_WINDOW])
        if day:
            return day
    return None


def _effective(text: str, enacted: date | None, promulgated: date | None) -> date | None:
    clauses = list(_IN_FORCE.finditer(text))
    if not clauses:
        return None
    last = clauses[-1]
    if last["on"]:
        return promulgated if last["on"].lower() == "diundangkan" else enacted
    return _first_date(last["date"])


def _first_date(text: str) -> date | None:
    for found in _DATE.finditer(text):
        try:
            return date(int(found[3]), MONTHS.index(found[2].lower()) + 1, int(found[1]))
        except ValueError:  # "31 Februari": a misprint or OCR error
            continue
    return None
