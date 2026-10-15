"""Aliases: every way people cite a document, kept so citations in other documents can be resolved."""

from __future__ import annotations

import re

from metamorph_contract import NormalizedDocument

_SPACES = re.compile(r"\s+")


def alias_key(text: str) -> str:
    """The lookup form: case and spacing never decide whether two citations match."""
    return _SPACES.sub(" ", text).strip().lower()


def aliases_of(document: NormalizedDocument) -> dict[str, str]:
    """{key: text} for the document's citation and its aliases."""
    texts = [document.document.citation, *document.document.aliases]
    return {alias_key(text): text for text in texts if text.strip()}
