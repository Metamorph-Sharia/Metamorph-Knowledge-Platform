"""What each passage of a report or a release names: regulations and companies (market-data-layer-plan.md, Phase 5).

- **Regulations** are found by the regulation layer's one reference grammar (references.py): a miss is fixed there,
  for both layers. A reference that names no instrument isn't a mention.
- **Companies** are found by their full legal names, whatever the case or punctuation ("PT. INVESTREE RADHIKA JAYA"
  names PT Investree Radhika Jaya), never inside a longer name and never by an abbreviation or a platform name.

A mention says "names", never "revokes" or "issues": what a passage did is in its words. Each target is mentioned
once a passage, as first written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from metamorph_platform.domain.market.publication import PublishedCompany
from metamorph_platform.domain.references import references

TOKEN = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Passage:
    kind: str  # report or release
    document: str  # its ID
    address: str
    text: str


@dataclass(frozen=True)
class Mention:
    kind: str  # the document's: report or release
    document: str
    address: str  # the passage's
    target_kind: str  # regulation or company
    target: str  # a regulation's ID or a company's
    words: str  # as written


def mentions(passages: Iterable[Passage], companies: Sequence[PublishedCompany]) -> list[Mention]:
    names = _Names(companies)
    found: list[Mention] = []
    for passage in passages:
        named = [("regulation", reference.target_id, reference.text) for reference in references(passage.text)
                 if reference.target_id]
        named += names.found(passage.text)
        seen: set[tuple[str, str]] = set()
        for target_kind, target, words in named:
            if (target_kind, target) not in seen:
                seen.add((target_kind, target))
                found.append(Mention(passage.kind, passage.document, passage.address, target_kind, target, words))
    return found


class _Names:
    """Every company's legal name as one pattern: its words in order, anything but letters and digits between."""

    def __init__(self, companies: Sequence[PublishedCompany]) -> None:
        self.by_words: dict[tuple[str, ...], list[str]] = {}
        for company in companies:
            self.by_words.setdefault(_words(company.legal_name), []).append(company.id)
        alternatives = sorted((r"[\W_]+".join(map(re.escape, words)) for words in self.by_words if words),
                              key=len, reverse=True)
        self.pattern = re.compile(rf"(?<![^\W_])(?:{'|'.join(alternatives)})(?![^\W_])", re.I) if alternatives else None

    def found(self, text: str) -> list[tuple[str, str, str]]:
        if self.pattern is None:
            return []
        return [("company", company, match[0]) for match in self.pattern.finditer(text)
                for company in self.by_words.get(_words(match[0]), [])]


def _words(name: str) -> tuple[str, ...]:
    return tuple(word.casefold() for word in TOKEN.findall(name))
