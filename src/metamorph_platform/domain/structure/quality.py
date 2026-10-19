"""Does a parsed tree look like the instrument it came from? Each problem makes the text a `structure_suspect`.

Articles and paragraphs are numbered 1, 2, 3 … in every instrument, so a gap means the text lost a
heading (usually at a page break) or the parser misread one. An elucidation explains the body's
articles, so an elucidation of an article the body lacks means the same. An amendment may quote an
article only from the paragraph it changes, so a quoted article is checked from its first paragraph.
"""

from __future__ import annotations

from collections import defaultdict

from metamorph_platform.domain.structure.grammars import article_key
from metamorph_platform.domain.structure.model import Node
from metamorph_platform.domain.structure.text import is_roman, roman_value

ELUCIDATION_PREFIX = "penjelasan/"


def problems(grammar: str, nodes: tuple[Node, ...]) -> list[str]:
    if grammar == "peraturan":
        return _regulation_problems(nodes)
    if grammar == "surat_edaran":
        return _gaps("romawi", [roman_value(n.label.rstrip(".")) for n in nodes if n.kind == "romawi"])
    return []


def _regulation_problems(nodes: tuple[Node, ...]) -> list[str]:
    body = [node for node in nodes if node.kind == "pasal" and "/" not in node.address]  # not quoted in an amendment
    if not body:
        elucidation_only = any(node.kind == "penjelasan" for node in nodes)  # BI publishes some as their own file
        return [] if elucidation_only else ["no Pasal found"]
    arabic = [_number(node) for node in body if not is_roman(_number(node))]
    roman = [roman_value(_number(node)) for node in body if is_roman(_number(node))]
    found = [
        *_gaps("Pasal", sorted({article_key(number)[0] for number in arabic})),
        *_gaps("Pasal", roman, roman_numerals=True),
        *_paragraph_gaps(nodes),
    ]
    if not roman:  # an amending regulation's elucidation follows its own Roman articles
        held = {node.address for node in body}
        found += [
            f"{node.address} explains an article the body lacks"
            for node in nodes
            if _explains_article(node) and node.address[len(ELUCIDATION_PREFIX) :] not in held
        ]
    return found


def _paragraph_gaps(nodes: tuple[Node, ...]) -> list[str]:
    paragraphs: dict[str, list[int]] = defaultdict(list)
    for node in nodes:
        if node.kind == "ayat" and node.parent and not node.parent.startswith(ELUCIDATION_PREFIX):
            paragraphs[node.parent].append(int(node.label.strip("()")))
    return [
        f"{article}: ayat ({missing}) missing"
        for article, numbers in paragraphs.items()
        for missing in sorted(set(range(_first_expected(article, numbers), max(numbers) + 1)) - set(numbers))
    ]


def _first_expected(article: str, numbers: list[int]) -> int:
    """An article an amendment quotes ("pasal-i/pasal-2") may be quoted from the paragraph it changes."""
    return min(numbers) if "/" in article else 1


def _gaps(what: str, numbers: list[int], *, roman_numerals: bool = False) -> list[str]:
    if not numbers:
        return []
    missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
    return [f"{what} {_roman(n) if roman_numerals else n} missing" for n in missing]


def _number(node: Node) -> str:
    return node.label.split()[-1]


def _explains_article(node: Node) -> bool:
    return (
        node.kind == "penjelasan"
        and node.address.count("/") == 1
        and node.address.startswith(ELUCIDATION_PREFIX + "pasal-")
    )


def _roman(value: int) -> str:
    numerals = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    result = ""
    for amount, numeral in numerals:
        while value >= amount:
            result, value = result + numeral, value - amount
    return result
