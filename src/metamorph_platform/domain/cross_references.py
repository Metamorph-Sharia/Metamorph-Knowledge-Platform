"""References inside a document: "sebagaimana dimaksud dalam Pasal 19 ayat (2)", pointing at its own provision.

    Pasal 19 ayat (2)      pasal-19/ayat-2, or pasal-19 when the text has no such paragraph
    ayat (1)               a paragraph of the article the text is in, or of the article just named
                           ("Pasal 19 ayat (2) dan ayat (3)")
    Pasal 3 huruf a        pasal-3: letters and numbers inside an article aren't provisions

An article followed by another instrument's name ("Pasal 8 dan Pasal 9 Undang-Undang Nomor 21 Tahun 2011") is
that instrument's, and is left to the citations (domain/citations.py), unless the name is this document's own
("Pasal 20 Peraturan Otoritas Jasa Keuangan ini"). An amending regulation's quoted articles name the amended
regulation's articles, so nothing in them is linked here.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

_REFERENCE = re.compile(
    r"\b(?:Pasal\s+(?P<article>\d+[A-Z]?)(?:\s+ayat\s+\((?P<paragraph>\d+[a-z]?)\))?"
    r"|ayat\s+\((?P<alone>\d+[a-z]?)\))"
)
# What may sit between the articles of one list: "Pasal 8 dan Pasal 9", "ayat (2), ayat (3)", "huruf a".
_LIST = re.compile(r"(?:\s*(?:,|dan/atau|dan|atau|serta|sampai\s+dengan|s\.d\.|huruf\s+[a-z]|angka\s+\d+))*\s*")
_INSTRUMENT = re.compile(
    r"(?:Undang-Undang|Peraturan|Keputusan|Surat\s+Edaran|Instruksi|Fatwa|Kitab|UU|PP|Perpres|Perppu|POJK|SEOJK|"
    r"PBI|PADG|SEBI|PADK)\b"
)
_THIS_ONE = re.compile(r"[^.;:\n]{0,60}?\bini\b")  # "… Peraturan Otoritas Jasa Keuangan ini"
_STATED_ELSEWHERE = re.compile(r"[^.;:\n]{0,60}?\b(?:Nomor|No\.|Tahun)\b")
_AMENDING_ARTICLE = re.compile(r"^pasal-[ivxlc]+/")
_OWN_ARTICLE = re.compile(r"^(?:penjelasan/)?(pasal-[0-9a-z]+)")


@dataclass(frozen=True)
class CrossReference:
    start: int  # where the reference is in the text
    end: int
    address: str  # the provision it names


def cross_references(text: str, *, within: str | None, addresses: Collection[str]) -> list[CrossReference]:
    """The references in `text` (the wording of the provision `within`) to the provisions in `addresses`."""
    if within and _AMENDING_ARTICLE.match(within):
        return []
    own = _OWN_ARTICLE.match(within or "")
    article = own[1] if own else None  # the article a paragraph named alone belongs to
    found: list[CrossReference] = []
    pending: list[tuple[re.Match[str], str]] = []  # one list of articles, until what follows it is known
    last_end = None
    for match in _REFERENCE.finditer(text):
        if last_end is not None and not _LIST.fullmatch(text, last_end, match.start()):
            found.extend(_settled(text, pending, addresses))
            pending, article = [], own[1] if own else None
        if match["article"]:
            article = f"pasal-{match['article'].lower()}"
            target = f"{article}/ayat-{match['paragraph']}" if match["paragraph"] else article
        elif article:
            target = f"{article}/ayat-{match['alone']}"
        else:
            last_end = match.end()
            continue
        pending.append((match, target))
        last_end = match.end()
    found.extend(_settled(text, pending, addresses))
    return found


def _settled(text: str, pending: list[tuple[re.Match[str], str]], addresses: Collection[str]) -> list[CrossReference]:
    """A list of articles, linked unless another instrument's name follows it."""
    if not pending or _of_another_instrument(text, pending[-1][0].end()):
        return []
    linked = []
    for match, target in pending:
        address = target if target in addresses else target.split("/ayat-")[0]
        if address in addresses:
            linked.append(CrossReference(match.start(), match.end(), address))
    return linked


def _of_another_instrument(text: str, end: int) -> bool:
    after = _LIST.match(text, end)
    position = after.end() if after else end
    named = _INSTRUMENT.match(text, position)
    if not named:
        return False
    this_one = _THIS_ONE.match(text, named.end())
    elsewhere = _STATED_ELSEWHERE.match(text, named.end())
    named_as_this_one = this_one is not None and (elsewhere is None or this_one.end() < elsewhere.end())
    return not named_as_this_one
