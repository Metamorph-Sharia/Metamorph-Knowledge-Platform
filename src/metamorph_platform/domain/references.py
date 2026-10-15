"""Mentions of other instruments in a legal text ("Undang-Undang Nomor 21 Tahun 2011"), and the IDs they name.

Each issuer's numbering is read the way that issuer numbers (identity rules shared with the connectors):
  ojk   10/POJK.05/2019 or 11 Tahun 2022           → ojk:pojk:2019:10
  bi    22/23/PBI/2020 (volume 22 = 2020) or 1 Tahun 2025, SE 15/34/DPSP → bi:pbi:2020:23
  id    Nomor 21 Tahun 2011; PMK 130/PMK.010/2012   → id:uu:2011:21, id:pmk:2012:130
  fatwa 117/DSN-MUI/II/2018 (also "DSNMUI")         → dsnmui:fatwa:117

Words may be split across lines (BI's justified PDFs put one word per line), so any whitespace separates them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

FIRST_BI_VOLUME_YEAR = 1998  # BI volume 1 = 1999


@dataclass(frozen=True)
class Reference:
    start: int
    end: int
    text: str  # as written, whitespace collapsed
    target_id: str | None


def _words(*alternatives: str) -> str:
    return "|".join(r"\s+".join(alternative.split()) for alternative in alternatives)


_NAMES = {  # longest first where one name starts another
    "perppu": _words("Peraturan Pemerintah Pengganti Undang-Undang", "Perppu", "Perpu"),
    "uu": _words("Undang-Undang", r"Undang\s*Undang", r"\bUU"),
    "pp": _words("Peraturan Pemerintah", r"\bPP"),
    "perpres": _words("Peraturan Presiden", "Perpres"),
    "keppres": _words("Keputusan Presiden", "Keppres"),
    "pmk": _words("Peraturan Menteri Keuangan", r"\bPMK"),
    "padk": _words(
        "Peraturan Anggota Dewan Komisioner Otoritas Jasa Keuangan", "Peraturan Anggota Dewan Komisioner", r"\bPADK"
    ),  # fmt: skip
    "pojk": _words("Peraturan Otoritas Jasa Keuangan", r"\bPOJK"),
    "seojk": _words("Surat Edaran Otoritas Jasa Keuangan", r"\bSEOJK"),
    "pbi": _words("Peraturan Bank Indonesia", r"\bPBI"),
    "padg": _words("Peraturan Anggota Dewan Gubernur", r"\bPADG"),
    "sebi": _words("Surat Edaran Ekstern Bank Indonesia", "Surat Edaran Bank Indonesia", r"\bSEBI"),
}
_NUMBER = r"(?P<number>\d+\s+Tahun\s+\d{4}|\d+(?:\s*/\s*[A-Za-z0-9][A-Za-z0-9.\-]*)+)"
_NOMOR = r"\s+(?:Republik\s+Indonesia\s+)?(?:Nomor|No\.?)\s*:?\s*"
_FATWA = r"(?P<fatwa>(?P<sequence>\d{1,3})\s*/\s*DSN[\s-]*MUI\s*/\s*[IVX]+\s*/\s*\d{4})"
_MENTION = re.compile(
    "|".join(f"(?P<{family}>{name}){_NOMOR}" for family, name in _NAMES.items()).join(("(?:", ")")) + _NUMBER
    + "|" + _FATWA,
    re.IGNORECASE,
)  # fmt: skip
_FATWA_MENTION = re.compile(_FATWA, re.IGNORECASE)
_YEARLY = re.compile(r"^(\d+)\s+Tahun\s+(\d{4})$", re.IGNORECASE)
_YEAR = re.compile(r"^\d{4}$")

ISSUER = {"pojk": "ojk", "seojk": "ojk", "padk": "ojk", "pbi": "bi", "padg": "bi", "sebi": "bi"}  # else "id"


def references(text: str, start: int = 0, end: int | None = None) -> list[Reference]:
    """Mentions in text[start:end], with offsets into the whole text."""
    return [_reference(match) for match in _MENTION.finditer(text, start, len(text) if end is None else end)]


def fatwa_references(text: str) -> list[Reference]:
    """Only the fatwas: their numbers ("117/DSN-MUI/II/2018") are recognisable anywhere, and fast to find."""
    return [_reference(match) for match in _FATWA_MENTION.finditer(text)]


def _reference(match: re.Match[str]) -> Reference:
    written = " ".join(match[0].split())
    if match["fatwa"]:
        return Reference(match.start(), match.end(), written, f"dsnmui:fatwa:{int(match['sequence'])}")
    return Reference(match.start(), match.end(), written, _target_id(_family(match), match["number"]))


def _family(match: re.Match[str]) -> str:
    return next(family for family in _NAMES if match[family])


def _target_id(family: str, number: str) -> str | None:
    parsed = _NUMBERING.get(ISSUER.get(family, "id"), _national)(number)
    if parsed is None:
        return None
    sequence, year = parsed
    return f"{ISSUER.get(family, 'id')}:{family}:{year}:{sequence}"


def _yearly(number: str) -> tuple[int, int] | None:
    found = _YEARLY.match(" ".join(number.split()))
    return (int(found[1]), int(found[2])) if found else None


def _parts(number: str) -> list[str]:
    return [part.strip().rstrip(".") for part in number.split("/")]


def _national(number: str) -> tuple[int, int] | None:
    """Nomor 21 Tahun 2011; a ministerial 130/PMK.010/2012 carries its year last."""
    parts = _parts(number)
    if len(parts) > 1 and _YEAR.match(parts[-1]):
        return int(parts[0]), int(parts[-1])
    return _yearly(number)


def _ojk(number: str) -> tuple[int, int] | None:
    return _national(number)  # 10/POJK.05/2019 or 11 Tahun 2022: the same two shapes


def _bi(number: str) -> tuple[int, int] | None:
    """22/23/PBI/2020: volume/sequence/unit[/year]; the volume counts years from 1999."""
    parts = _parts(number)
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return _yearly(number)
    year = FIRST_BI_VOLUME_YEAR + int(parts[0])
    if _YEAR.match(parts[-1]) and int(parts[-1]) != year:
        return None
    return int(parts[1]), year


_NUMBERING: dict[str, Callable[[str], tuple[int, int] | None]] = {"ojk": _ojk, "bi": _bi, "id": _national}
