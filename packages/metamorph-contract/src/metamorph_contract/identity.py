"""Canonical document IDs: named by issuer, not by the source that found the document.

    ojk:pojk:2014:5        dsnmui:fatwa:117        id:uu:2011:21        bi:padg:2026:31
    {issuer}:{family}[:{year}]:{number}

A document whose identity a connector can't establish still loads, under
`unresolved:{connector}:{key}`, and goes to the curation queue.

The grammar and the issuers come from the JSON Schema, so they are defined once.
"""

from __future__ import annotations

import hashlib
import re

from metamorph_contract.schema import DOCUMENT_SCHEMA, load_schema

_DEFINITIONS = load_schema(DOCUMENT_SCHEMA)["$defs"]

KNOWN_ISSUERS = frozenset(_DEFINITIONS["issuer"]["enum"])
UNRESOLVED = "unresolved"

_CANONICAL = re.compile(_DEFINITIONS["canonicalId"]["pattern"])
_UNRESOLVED = re.compile(_DEFINITIONS["unresolvedId"]["pattern"])
_UNRESOLVED_KEY_LENGTH = 16


def canonical_id(issuer: str, family: str, number: str | int, year: int | None = None) -> str:
    """e.g. canonical_id("ojk", "pojk", 5, 2014) == "ojk:pojk:2014:5"; omit the year when numbers never repeat."""
    parts = [issuer, family, *([str(year)] if year is not None else []), str(number)]
    candidate = ":".join(part.strip().lower() for part in parts)
    if not is_canonical(candidate):
        raise ValueError(f"not a valid canonical ID: {candidate!r}")
    return candidate


def unresolved_id(connector: str, source_id: str) -> str:
    """A stable placeholder ID; the source_id is hashed because it may be a URL with spaces or slashes."""
    key = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:_UNRESOLVED_KEY_LENGTH]
    return f"{UNRESOLVED}:{connector.lower()}:{key}"


def is_canonical(value: str) -> bool:
    return bool(_CANONICAL.match(value))


def is_unresolved(value: str) -> bool:
    return bool(_UNRESOLVED.match(value))


def issuer_of(value: str) -> str:
    return value.split(":", 1)[0]
