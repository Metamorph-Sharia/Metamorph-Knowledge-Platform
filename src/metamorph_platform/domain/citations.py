"""Citations found in a document's own text, located by the structure parser's provisions.

    legal_basis     every instrument named in "Mengingat"
    adopts_fatwa    a numbered DSN-MUI fatwa cited anywhere (refers_to, when a fatwa cites a fatwa)
    revokes         "… dicabut dan dinyatakan tidak berlaku" in the body; partly_revokes when it names articles
    implements      "melaksanakan ketentuan Pasal 20 ayat (4) <instrument>" in the considerations, or a
                    circular's opening: one citation per article named
    amends          an amending regulation's "Beberapa ketentuan dalam <instrument> diubah …", and each
                    numbered instruction under it (diubah, disisipkan → amends; dihapus → partly_revokes)

Elucidations and annexes only explain or illustrate, so revocations there are not the document's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from metamorph_contract import Relation

from metamorph_platform.domain.references import Reference, fatwa_references, references
from metamorph_platform.domain.structure import Node, Structure
from metamorph_platform.domain.structure.text import is_roman

EVIDENCE_CONTEXT = 120  # characters either side of the mention
FATWA_PREFIX = "dsnmui:fatwa:"
NOT_THE_BODY = ("penjelasan", "lampiran")

_REVOKED = re.compile(
    r"dicabut\s+dan\s+dinyatakan\s+tidak\s+berlaku|dinyatakan\s+dicabut|dicabut\s+dan\s+tidak\s+berlaku", re.IGNORECASE
)
_CLAUSE_END = re.compile(r";|\.\s*\n")
_IMPLEMENTING = re.compile(r"melaksanakan\s+ketentuan|pelaksanaan\s+(?:amanat\s+)?ketentuan", re.IGNORECASE)
_ARTICLE = re.compile(r"\bPasal\s+(\d+[A-Z]?)(?:\s+ayat\s+\((\d+)\))?")
_AMENDING = re.compile(r"diubah\s+(?:sebagai\s+berikut|sehingga)", re.IGNORECASE)
_INSTRUCTION = re.compile(r"(?m)^\s*\d+\.\s+")
_INSERTED = re.compile(r"\b(?:yakni|yaitu)\s+Pasal\s+(\d+[A-Z]?)", re.IGNORECASE)


@dataclass(frozen=True)
class TextCitation:
    relation: Relation
    target_text: str
    target_id: str | None
    evidence: str
    from_address: str | None = None
    to_address: str | None = None


def text_citations(text: str, structure: Structure, *, document_id: str) -> list[TextCitation]:
    found = [
        *_legal_basis(text, structure.nodes),
        *_fatwas(text, structure.nodes, citing_fatwa=document_id.startswith(FATWA_PREFIX)),
        *_revocations(text, structure.nodes),
        *_implementations(text, structure),
        *_amendments(text, structure.nodes),
    ]
    unique = {(c.relation, c.target_id or c.target_text, c.from_address, c.to_address): c for c in reversed(found)}
    return [c for c in found if unique.get(_key(c)) is c and c.target_id != document_id]


def _key(citation: TextCitation) -> tuple:
    return citation.relation, citation.target_id or citation.target_text, citation.from_address, citation.to_address


def _legal_basis(text: str, nodes: tuple[Node, ...]) -> list[TextCitation]:
    basis = next((node for node in nodes if node.address == "mengingat"), None)
    if basis is None:
        return []
    return [_citation(Relation.LEGAL_BASIS, ref, text) for ref in references(text, basis.char_start, basis.char_end)]


def _fatwas(text: str, nodes: tuple[Node, ...], *, citing_fatwa: bool) -> list[TextCitation]:
    relation = Relation.REFERS_TO if citing_fatwa else Relation.ADOPTS_FATWA
    found = []
    for ref in fatwa_references(text):
        node = _innermost(nodes, ref.start)
        if node is None or node.address != "mengingat":
            found.append(_citation(relation, ref, text, from_address=node.address if node else None))
    return found


def _revocations(text: str, nodes: tuple[Node, ...]) -> list[TextCitation]:
    found = []
    for phrase in _REVOKED.finditer(text):
        node = _innermost(nodes, phrase.start())
        if node is None or node.address.startswith(NOT_THE_BODY):
            continue
        clause_start = _clause_start(text, _after_heading(text, node), phrase.start())
        for ref in references(text, clause_start, phrase.start()):
            articles = [_address(match) for match in _ARTICLE.finditer(text, clause_start, ref.start)]
            if not articles:
                found.append(_citation(Relation.REVOKES, ref, text, from_address=node.address))
            for article in articles:
                found.append(
                    _citation(Relation.PARTLY_REVOKES, ref, text, from_address=node.address, to_address=article)
                )
    return found


def _implementations(text: str, structure: Structure) -> list[TextCitation]:
    considerations = next((node for node in structure.nodes if node.address == "menimbang"), None)
    if considerations:
        start, end = considerations.char_start, considerations.char_end
    elif structure.grammar == "surat_edaran":  # a circular says what it implements before its first section
        start, end = 0, structure.nodes[0].char_start if structure.nodes else len(text)
    else:
        return []
    found = []
    for phrase in _IMPLEMENTING.finditer(text, start, end):
        clause_end = _clause_end(text, phrase.end(), end)
        target = next(iter(references(text, phrase.end(), clause_end)), None)
        if target is None:
            continue
        articles = [_address(match) for match in _ARTICLE.finditer(text, phrase.end(), target.start)]
        found += [_citation(Relation.IMPLEMENTS, target, text, to_address=article) for article in articles or [None]]
    return found


def _amendments(text: str, nodes: tuple[Node, ...]) -> list[TextCitation]:
    found = []
    for article in nodes:
        if article.kind != "pasal" or "/" in article.address or not is_roman(article.label.split()[-1]):
            continue
        own = _own_text(text, article, nodes)
        intro, *instructions = _INSTRUCTION.split(own)
        if not _AMENDING.search(own):
            continue
        target = next(iter(references(intro)), None)
        if target is None:
            continue
        found.append(_citation(Relation.AMENDS, target, intro, from_address=article.address))
        for instruction in instructions:
            changed = _changed_article(instruction)
            if changed:
                relation = Relation.PARTLY_REVOKES if re.search(r"\bdihapus\b", instruction) else Relation.AMENDS
                found.append(_citation(relation, target, instruction, from_address=article.address, to_address=changed))
    return found


def _changed_article(instruction: str) -> str | None:
    inserted = _INSERTED.search(instruction)
    if inserted:
        return f"pasal-{inserted[1].lower()}"
    first = _ARTICLE.search(instruction)
    return f"pasal-{first[1].lower()}" if first else None


def _own_text(text: str, node: Node, nodes: tuple[Node, ...]) -> str:
    """The node's text without its descendants': an amending article's instructions, not what it quotes."""
    pieces, cursor = [], node.char_start
    for child in sorted((n for n in nodes if n.parent == node.address), key=lambda n: n.char_start):
        pieces.append(text[cursor : child.char_start])
        cursor = child.char_end
    pieces.append(text[cursor : node.char_end])
    return "\n".join(pieces)


def _innermost(nodes: tuple[Node, ...], offset: int) -> Node | None:
    containing = [node for node in nodes if node.char_start <= offset < node.char_end]
    return max(containing, key=lambda node: node.char_start, default=None)


def _after_heading(text: str, node: Node) -> int:
    """Where the node's content begins: its heading ("Pasal 2", or "(1)" before the paragraph's own words)
    names the node, not a revoked article."""
    if node.kind == "ayat":
        return node.char_start + len(node.label)
    end_of_heading = text.find("\n", node.char_start, node.char_end)
    return node.char_end if end_of_heading < 0 else end_of_heading + 1


def _clause_start(text: str, floor: int, offset: int) -> int:
    ends = [match.end() for match in _CLAUSE_END.finditer(text, floor, offset)]
    return ends[-1] if ends else floor


def _clause_end(text: str, offset: int, ceiling: int) -> int:
    found = _CLAUSE_END.search(text, offset, ceiling)
    return found.start() if found else ceiling


def _address(article: re.Match[str]) -> str:
    return f"pasal-{article[1].lower()}" + (f"/ayat-{article[2]}" if article[2] else "")


def _citation(
    relation: Relation, ref: Reference, text: str, *, from_address: str | None = None, to_address: str | None = None
) -> TextCitation:
    """`text` is what `ref`'s offsets point into; the evidence is the passage around the mention."""
    passage = text[max(0, ref.start - EVIDENCE_CONTEXT) : ref.end + EVIDENCE_CONTEXT]
    return TextCitation(relation, ref.text, ref.target_id, " ".join(passage.split()), from_address, to_address)
