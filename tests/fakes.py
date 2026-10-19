"""In-memory stand-ins for every port, so use cases are tested without PostgreSQL or S3."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metamorph_contract import Manifest, NormalizedDocument

from metamorph_platform.application.ports import (
    BundleAlreadyLoaded,
    Curator,
    NewLink,
    OpenCitation,
    OpenReview,
    ParsedText,
    StoredBlob,
    TextToParse,
)
from metamorph_platform.domain.curation import ActiveOverride
from metamorph_platform.domain.health import Health, HealthFacts
from metamorph_platform.domain.loading import ReviewKind, SaveOutcome
from metamorph_platform.domain.publishing import DocumentSnapshot, PublishedDocument
from metamorph_platform.domain.reviews import TextStanding
from metamorph_platform.domain.validity import DatedLink, ProvisionExpiry, StatusChange


class MemoryBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.writes = 0

    def store(self, sha256: str, source: Path, media_type: str) -> StoredBlob:
        if sha256 not in self.blobs:
            self.blobs[sha256] = source.read_bytes()
            self.writes += 1
        return StoredBlob(sha256, f"blobs/{sha256[:2]}/{sha256}", media_type, len(self.blobs[sha256]))

    def read(self, storage_key: str) -> bytes:
        return self.blobs[storage_key.rsplit("/", 1)[-1]]


class MemoryLedger:
    def __init__(self) -> None:
        self.bundles: dict[int, dict[str, Any]] = {}
        self.quarantined: list[dict[str, Any]] = []

    def start_bundle(self, manifest: Manifest, uri: str) -> int:
        if any(b["run"] == (manifest.connector, manifest.run_id) for b in self.bundles.values()):
            raise BundleAlreadyLoaded(f"{manifest.connector} run {manifest.run_id}")
        bundle_id = len(self.bundles) + 1
        self.bundles[bundle_id] = {"run": (manifest.connector, manifest.run_id), "state": "received"}
        return bundle_id

    def quarantine(self, bundle_id: int, line: int, raw: str, problems: list[str], source_id: str | None) -> None:
        self.quarantined.append({"bundle_id": bundle_id, "line": line, "problems": problems, "source_id": source_id})

    def finish_bundle(self, bundle_id: int, counts: Mapping[str, int]) -> None:
        self.bundles[bundle_id].update(state="loaded", counts=dict(counts))

    def fail_bundle(self, bundle_id: int, error: str) -> None:
        self.bundles[bundle_id].update(state="failed", error=error)


class MemoryRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.assignments: dict[tuple[str, str], str] = {}

    def assigned_id(self, connector: str, source_id: str) -> str | None:
        return self.assignments.get((connector, source_id))

    def package_hash(self, connector: str, source_id: str) -> str | None:
        record = self.records.get((connector, source_id))
        return record["package_hash"] if record else None

    def seen_again(self, connector: str, source_id: str, bundle_id: int) -> None:
        self.records[(connector, source_id)].update(missing=False, bundle_id=bundle_id)

    def save(self, document: NormalizedDocument, *, bundle_id: int, package_hash: str, blobs) -> SaveOutcome:
        key = (document.source.connector, document.source.source_id)
        outcome = SaveOutcome.CHANGED if key in self.records else SaveOutcome.NEW
        self.records[key] = {
            "document": document,
            "package_hash": package_hash,
            "blobs": dict(blobs),
            "bundle_id": bundle_id,
            "missing": False,
        }
        return outcome

    def mark_missing(self, connector: str, present: set[str]) -> int:
        newly = 0
        for (owner, source_id), record in self.records.items():
            if owner == connector and source_id not in present and not record["missing"]:
                record["missing"] = True
                newly += 1
        return newly


class MemoryOverrides:
    def __init__(self) -> None:
        self.active_by_document: dict[str, list[ActiveOverride]] = {}
        self.raised: list[tuple[int, Any]] = []

    def active(self, document_id: str) -> list[ActiveOverride]:
        return self.active_by_document.get(document_id, [])

    def raise_conflict(self, override_id: int, source_value: Any) -> None:
        self.raised.append((override_id, source_value))


class MemoryReviewQueue:
    def __init__(self) -> None:
        self.open: list[tuple[ReviewKind, dict[str, Any]]] = []

    def ensure_open(self, kind: ReviewKind, subject: Mapping[str, Any]) -> None:
        if (kind, dict(subject)) not in self.open:
            self.open.append((kind, dict(subject)))


class MemoryPublication:
    """Both sides of publishing: the snapshots to read and the published rows written."""

    def __init__(self, snapshots: dict[str, DocumentSnapshot]) -> None:
        self.snapshots = snapshots
        self.published: dict[str, PublishedDocument] = {}

    def documents_to_publish(self, everything: bool = False) -> list[str]:
        return sorted(set(self.snapshots) | set(self.published))

    def snapshot(self, document_id: str) -> DocumentSnapshot | None:
        return self.snapshots.get(document_id)

    def replace(self, document: PublishedDocument) -> bool:
        is_new = document.id not in self.published
        self.published[document.id] = document
        return is_new

    def remove(self, document_id: str) -> bool:
        return self.published.pop(document_id, None) is not None


class MemoryBlobReader:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.reads: list[str] = []

    def read(self, storage_key: str) -> bytes:
        self.reads.append(storage_key)
        return self.blobs[storage_key]


class MemoryParsedTexts:
    def __init__(self, texts: list[TextToParse]) -> None:
        self.texts = texts
        self.saved: list[ParsedText] = []

    def texts_to_parse(self, parser_version: str, everything: bool = False) -> list[TextToParse]:
        done = {(p.text.text_version_id, p.parser_version) for p in self.saved}
        return [t for t in self.texts if everything or (t.text_version_id, parser_version) not in done]

    def save(self, parsed: ParsedText) -> None:
        self.saved.append(parsed)


class MemoryCitationLinks:
    def __init__(self, *, open: list[OpenCitation], documents: set[str], aliases: dict[str, str] | None = None) -> None:
        self.open = open
        self.documents = documents
        self.aliases = aliases or {}
        self.linked: list[tuple[int, NewLink]] = []

    def open_citations(self) -> list[OpenCitation]:
        linked = {citation_id for citation_id, _ in self.linked}
        return [c for c in self.open if c.id not in linked]

    def document_ids(self) -> set[str]:
        return self.documents

    def unambiguous_aliases(self) -> dict[str, str]:
        return self.aliases

    def link(self, citation_id: int, link: NewLink) -> None:
        self.linked.append((citation_id, link))

    def drop_unsupported_links(self) -> int:
        return 0


class MemoryValidity:
    def __init__(self, links: list[DatedLink]) -> None:
        self.links = links
        self.applied: tuple[list[StatusChange], list[ProvisionExpiry]] | None = None

    def dated_links(self) -> list[DatedLink]:
        return self.links

    def apply(self, changes: list[StatusChange], expiries: list[ProvisionExpiry]) -> int:
        self.applied = (changes, expiries)
        return len({change.document_id for change in changes} | {expiry.document_id for expiry in expiries})


class MemoryHealth:
    def __init__(self, facts: HealthFacts) -> None:
        self._facts = facts
        self.recorded: list[Health] = []

    def facts(self) -> HealthFacts:
        return self._facts

    def record(self, health: Health) -> None:
        self.recorded.append(health)


class MemoryCurationActions:
    """Records each action as (curator, action, target, after, reason): what the audit log would hold."""

    def __init__(self) -> None:
        self.calls: list[tuple[Curator, str, dict, Any, str]] = []

    def correct(self, curator, document_id, field, value, reason):
        self.record(curator, "correct", {"document_id": document_id, "field": field}, {"value": value}, reason)

    def withdraw_correction(self, curator, document_id, field, reason):
        self.record(curator, "withdraw_correction", {"document_id": document_id, "field": field}, None, reason)

    def suppress(self, curator, document_id, reason):
        self.record(curator, "suppress", {"document_id": document_id}, {"suppressed": True}, reason)

    def restore(self, curator, document_id, reason):
        self.record(curator, "restore", {"document_id": document_id}, {"suppressed": False}, reason)

    def decide_review(self, curator, item_id, state, note):
        self.record(curator, "decide_review", {"review_item_id": item_id}, {"state": state}, note)

    def assign_id(self, curator, document_id, new_id, reason):
        self.record(curator, "assign_id", {"document_id": document_id}, {"document_id": new_id}, reason)

    def link_citation(self, curator, citation_id, target_id, reason):
        self.record(curator, "link_citation", {"citation_id": citation_id}, {"to_document": target_id}, reason)

    def resolve_conflict(self, curator, conflict_id, state, note):
        self.record(curator, "resolve_conflict", {"conflict_id": conflict_id}, {"state": state}, note)

    def record(self, curator, action, target, after, reason):
        self.calls.append((curator, action, dict(target), after, reason))


class MemoryOpenReviews:
    """Open review items, and the registry facts that decide them."""

    def __init__(self, items: list[OpenReview]) -> None:
        self.items = items
        self.standings: dict[tuple[str, str], TextStanding] = {}
        self.unlinked: set[tuple[str, str]] = set()
        self.documents: set[str] = set()
        self.settled: dict[int, str] = {}

    def open_items(self) -> list[OpenReview]:
        return [item for item in self.items if item.id not in self.settled]

    def text_standing(self, document_id: str, text_sha256: str) -> TextStanding | None:
        return self.standings.get((document_id, text_sha256))

    def still_unlinked(self, document_id: str, target_text: str) -> bool:
        return (document_id, target_text) in self.unlinked

    def document_exists(self, document_id: str) -> bool:
        return document_id in self.documents

    def settle(self, item_id: int, reason: str) -> None:
        self.settled[item_id] = reason
