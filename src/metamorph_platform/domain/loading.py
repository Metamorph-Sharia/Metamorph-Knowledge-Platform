"""Rules for taking a connector's document into the registry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from metamorph_contract import Confidence, NormalizedDocument, is_unresolved, to_json

# Texts are UTF-8 with "<!-- page N -->" markers: plain text that renders as Markdown.
TEXT_MEDIA_TYPE = "text/markdown; charset=utf-8"


class ReviewKind(StrEnum):
    UNRESOLVED_ID = "unresolved_id"
    QUARANTINE = "quarantine"
    CONFLICT = "conflict"
    UNRESOLVED_CITATION = "unresolved_citation"
    STRUCTURE_SUSPECT = "structure_suspect"


class SaveOutcome(StrEnum):
    NEW = "new"  # first time this source record was loaded
    CHANGED = "changed"


@dataclass(frozen=True)
class BlobNeed:
    sha256: str
    media_type: str


def package_hash(document: NormalizedDocument) -> str:
    """Identical documents hash identically, so an unchanged line is recognised and skipped."""
    return hashlib.sha256(to_json(document).encode("utf-8")).hexdigest()


def blobs_needed(document: NormalizedDocument) -> list[BlobNeed]:
    needs = [BlobNeed(f.sha256, f.media_type) for f in document.files]
    needs += [BlobNeed(t.sha256, TEXT_MEDIA_TYPE) for t in document.texts]
    return needs


def needs_identity_review(document: NormalizedDocument) -> bool:
    """A person must name a document its connector could not identify, or that collided with another."""
    return is_unresolved(document.document.id) or document.document.id_confidence is Confidence.CONFLICT
