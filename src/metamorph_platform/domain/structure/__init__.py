"""The shared structure parser: any source's legal text → addressable provisions, with quality checks.

    parse(text, grammar_for("ojk", "pojk"))  →  Structure(nodes=(Node("pasal-5/ayat-1", …), …), problems=[…])

Addresses: pasal-115/ayat-1, bab-ii/bagian-kesatu, penjelasan/pasal-115, lampiran-i/bab-ii,
pasal-i/pasal-115 (an article an amending regulation quotes), romawi-ii (a circular's section),
diktum-kedua (a fatwa's ruling).
"""

from __future__ import annotations

from metamorph_platform.domain.structure.builder import TreeBuilder
from metamorph_platform.domain.structure.grammars import GRAMMARS
from metamorph_platform.domain.structure.model import PARSER_VERSION, Node, Structure
from metamorph_platform.domain.structure.quality import problems
from metamorph_platform.domain.structure.text import lines

CIRCULARS = {("ojk", "seojk"), ("bi", "sebi")}

__all__ = ["PARSER_VERSION", "Node", "Structure", "grammar_for", "parse"]


def grammar_for(issuer: str, family: str) -> str:
    if issuer == "dsnmui":
        return "fatwa"
    return "surat_edaran" if (issuer, family) in CIRCULARS else "peraturan"


def parse(text: str, grammar: str) -> Structure:
    builder = TreeBuilder(text)
    recogniser = GRAMMARS[grammar](builder)
    for line in lines(text):
        recogniser.feed(line)
        builder.passed(line)
    nodes = builder.nodes()
    return Structure(grammar=grammar, nodes=nodes, problems=problems(grammar, nodes))
