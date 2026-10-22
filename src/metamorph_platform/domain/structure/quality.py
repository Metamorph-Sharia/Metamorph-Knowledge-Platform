"""Does a parsed tree look like the instrument it came from? Each problem makes the text a `structure_suspect`.

Only one problem is material: a regulation with no article found has no provision to retrieve or cite, and is held
(domain/gate.py). A gap is a warning: a heading lost or misread costs a unit's boundary, not its words, so the text is
published and the gap noted for review.

Articles and paragraphs are numbered 1, 2, 3 … in every instrument, so a gap means the text lost a
heading (usually at a page break) or the parser misread one. An elucidation explains the body's
articles, so an elucidation of an article the body lacks means the same. An amendment may quote an
article only from the paragraph it changes, so a quoted article (and paragraphs an amending article quotes
without their article's heading) is checked from its first paragraph.
"""

from __future__ import annotations

from collections import defaultdict

from metamorph_platform.domain.structure.model import Node
from metamorph_platform.domain.structure.text import article_key, is_roman, roman_value

ELUCIDATION_PREFIX = "penjelasan/"
NO_ARTICLES = "no Pasal found"
_EXPLAINS_A_LOST_ARTICLE = " explains an article the body lacks"


def is_material(problem: str) -> bool:
    return problem == NO_ARTICLES


def affected_address(problem: str) -> str | None:
    """The provision a problem is about, when it names one: "pasal-4: ayat (2) missing" is about pasal-4. An
    article missing ("Pasal 9 missing") has no provision of its own."""
    if problem.endswith(_EXPLAINS_A_LOST_ARTICLE):
        return problem.removesuffix(_EXPLAINS_A_LOST_ARTICLE)
    address, colon, _ = problem.partition(": ")
    return address if colon else None


def circular_problems(nodes: tuple[Node, ...]) -> list[str]:
    return _gaps("romawi", [roman_value(n.label.rstrip(".")) for n in nodes if n.kind == "romawi"])


def regulation_problems(nodes: tuple[Node, ...]) -> list[str]:
    body = [node for node in nodes if node.kind == "pasal" and "/" not in node.address]  # not quoted in an amendment
    if not body:
        elucidation_only = any(node.kind == "penjelasan" for node in nodes)  # BI publishes some as their own file
        return [] if elucidation_only else [NO_ARTICLES]
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
            f"{node.address}{_EXPLAINS_A_LOST_ARTICLE}"
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
    """An article an amendment quotes ("pasal-i/pasal-2") may be quoted from the paragraph it changes, and so
    may the paragraphs an instruction quotes without their article's heading, which nest in "pasal-i" itself:
    an amending article has no paragraphs of its own."""
    quoted = "/" in article or is_roman(article.removeprefix("pasal-"))
    return min(numbers) if quoted else 1


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
