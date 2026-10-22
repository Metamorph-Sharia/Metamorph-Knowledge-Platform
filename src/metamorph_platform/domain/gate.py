"""The publish gate: what a document must pass to be published, and why it is held when it doesn't.

    identity   its ID is canonical, not a connector's placeholder
    text       it has a main text: the Indonesian text of its main file (or one with no file)
    parsed     today's parser has read each main text, as it is now (a curator's correction included)
    structure  no main text has a material structure problem (a regulation with no article found), or a
               curator approved the problems it has as they are (an approval holds for exactly that text and
               those problems). A gap in the numbering is a warning, not a hold: it is published for review.

A held document keeps the version last published, if any: only a version that passed is ever written.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from metamorph_contract import is_unresolved

from metamorph_platform.domain.structure.quality import is_material


class Check(StrEnum):
    IDENTITY = "identity"
    TEXT = "text"
    PARSED = "parsed"
    STRUCTURE = "structure"


@dataclass(frozen=True)
class MainText:
    """A main text of the document, as the parser last read it."""

    sha256: str  # its effective content: a curator's correction of it, or the source's text
    parsed_sha256: str | None  # the content the parser last read; None until parsed
    parsed_with: str | None  # the parser version; None until parsed
    problems: tuple[str, ...]


@dataclass(frozen=True)
class Approval:
    """A curator's "publish as it is" for one text with exactly these problems: its warnings are reviewed too."""

    text_sha256: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class HoldReason:
    check: Check
    detail: str


def hold_reasons(
    document_id: str,
    main_texts: Sequence[MainText],
    approvals: Iterable[Approval],
    *,
    acquired_roles: Iterable[str],
    parser_version: str,
) -> tuple[HoldReason, ...]:
    """Why the document is held; empty when it may be published."""
    approved = set(approvals)
    held = []
    if is_unresolved(document_id):
        held.append(HoldReason(Check.IDENTITY, "No canonical ID yet: assign one"))
    if not main_texts:
        held.append(HoldReason(Check.TEXT, _no_main_text(acquired_roles)))
    for text in main_texts:
        if text.parsed_with != parser_version or text.parsed_sha256 != text.sha256:
            held.append(HoldReason(Check.PARSED, f"Not parsed with parser {parser_version} yet"))
        elif unapproved := _material_problems_unapproved(text, approved):
            held.append(HoldReason(Check.STRUCTURE, "; ".join(unapproved)))
    return tuple(held)


def _material_problems_unapproved(text: MainText, approved: set[Approval]) -> list[str]:
    material = [problem for problem in text.problems if is_material(problem)]
    return [] if Approval(text.sha256, text.problems) in approved else material


def _no_main_text(acquired_roles: Iterable[str]) -> str:
    roles = sorted(set(acquired_roles))
    return f"No main text: only {', '.join(roles)} acquired" if roles else "No main text, and no file acquired"
