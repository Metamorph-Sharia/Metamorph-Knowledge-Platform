"""When an open review item no longer needs a person: the cause it was opened for is gone.

Each rule takes what the registry now holds and returns the reason to record for settling the item, or
None while a person is still needed. An item is only ever settled for a cause that went away by itself
(a newer text, a re-parse, a later load); a conflict or a quarantined line always waits for a person.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_PROBLEMS_SHOWN = 20  # a structure item lists a text's first problems, not a cascade's thousands


@dataclass(frozen=True)
class TextStanding:
    """What the registry now holds for the text a structure item is about."""

    current: bool  # still the document's current text, not replaced by a newer version
    main: bool  # the document's main text, the one whose structure is parsed
    parsed_with: str | None  # the parser version that last read it
    problems: tuple[str, ...]


def structure_settlement(standing: TextStanding | None, queued: Sequence[str], parser_version: str) -> str | None:
    if standing is None or not standing.current:
        return "the text was replaced by a newer version"
    if not standing.main:
        return "the file is not the document's main text, so its structure isn't parsed"
    if standing.parsed_with != parser_version:
        return None  # today's parser hasn't read it yet: the next build will
    if not standing.problems:
        return f"parsed again with parser {parser_version}: no structure problems"
    if standing.problems[:MAX_PROBLEMS_SHOWN] != tuple(queued):
        return f"superseded: parser {parser_version} found other problems, queued as their own item"
    return None


def citation_settlement(*, still_unlinked: bool) -> str | None:
    return None if still_unlinked else "the citation was linked, or the text no longer cites it"


def identity_settlement(*, document_exists: bool) -> str | None:
    return None if document_exists else "the document no longer exists under its placeholder ID"
