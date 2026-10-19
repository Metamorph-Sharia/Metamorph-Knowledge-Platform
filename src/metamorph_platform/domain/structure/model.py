"""What the parser produces: a tree of addressable provisions over one text, and what looks wrong with it."""

from __future__ import annotations

from dataclasses import dataclass, field

PARSER_VERSION = "3"  # bump when a grammar changes, so every text is parsed again


@dataclass(frozen=True)
class Node:
    """One provision: e.g. address "pasal-5/ayat-1", kind "ayat", label "(1)", text[char_start:char_end]."""

    address: str
    kind: str  # menimbang | mengingat | bab | bagian | paragraf | pasal | ayat | penjelasan | lampiran | romawi …
    label: str
    char_start: int
    char_end: int
    ordinal: int  # reading order within the text
    parent: str | None = None
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class Structure:
    grammar: str
    nodes: tuple[Node, ...]
    problems: list[str] = field(default_factory=list)  # empty when the tree passes every quality check
