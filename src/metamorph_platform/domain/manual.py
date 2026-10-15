"""A document a curator enters by hand, as a contract v2 document of the `manual` connector.

Its fields are checked together, so the form can show every problem at once, each beside its field.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from metamorph_contract import (
    CONTRACT_VERSION,
    Confidence,
    Dates,
    DocumentInfo,
    ExtractionMethod,
    FileRef,
    FileRole,
    Kind,
    NormalizedDocument,
    Rights,
    SourceRef,
    Status,
    StatusClaim,
    TextOrigin,
    TextRef,
)

from metamorph_platform.domain.curation import InvalidCorrection, id_parts, parse_correction, validate_assigned_id

CONNECTOR = "manual"
DATE_FIELDS = ("enacted_on", "promulgated_on", "effective_on")


class InvalidManualDocument(ValueError):
    def __init__(self, problems: dict[str, str]) -> None:
        super().__init__("; ".join(f"{name}: {message}" for name, message in problems.items()))
        self.problems = problems


@dataclass(frozen=True)
class ManualDocument:
    """What the curator entered: the form's fields and the uploaded file."""

    document_id: str
    citation: str
    title: str
    kind: str
    status: str
    language: str
    source_url: str  # where the curator got the document
    file_name: str
    file_bytes: bytes
    media_type: str
    reason: str
    text: str = ""  # optional: the document's text, typed or pasted
    rights: str = "public"
    enacted_on: str = ""
    promulgated_on: str = ""
    effective_on: str = ""


def manual_document(entry: ManualDocument, *, author: str, fetched_at: str, version: str) -> NormalizedDocument:
    """The contract document for `entry`, or InvalidManualDocument naming every field that is wrong."""
    checked = _checked(entry)
    issuer, family, year, number = id_parts(checked["document_id"])
    file_sha = hashlib.sha256(entry.file_bytes).hexdigest()
    rights = Rights(checked["rights"])
    return NormalizedDocument(
        source=SourceRef(
            connector=CONNECTOR,
            connector_version=version,
            source_id=f"{CONNECTOR}:{checked['document_id']}",
            url=checked["source_url"],
            fetched_at=fetched_at,
        ),
        document=DocumentInfo(
            id=checked["document_id"],
            id_confidence=Confidence.HIGH,
            id_evidence=f"entered by curator {author}",
            issuer=issuer,
            family=family,
            number=number,
            year=year,
            citation=checked["citation"],
            title=checked["title"],
            language=checked["language"],
            kind=Kind(checked["kind"]),
            status=StatusClaim(value=Status(checked["status"]), source=CONNECTOR),
            dates=Dates(
                enacted=checked["enacted_on"], promulgated=checked["promulgated_on"], effective=checked["effective_on"]
            ),
        ),
        files=(
            FileRef(
                sha256=file_sha,
                role=FileRole.MAIN,
                media_type=entry.media_type or "application/octet-stream",
                source_url=checked["source_url"],
                rights=rights,
                title=entry.file_name or None,
            ),
        ),
        texts=_texts(entry, rights, file_sha, checked["language"]),
        source_fields={"entered_by": author, "reason": entry.reason, "file_name": entry.file_name},
        contract_version=CONTRACT_VERSION,
    )


def text_of(entry: ManualDocument) -> str | None:
    text = entry.text.strip()
    return f"{text}\n" if text else None


def _texts(entry: ManualDocument, rights: Rights, file_sha: str, language: str) -> tuple[TextRef, ...]:
    text = text_of(entry)
    if text is None:
        return ()
    return (
        TextRef(
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            language=language,
            origin=TextOrigin.SOURCE_TEXT,
            method=ExtractionMethod.SOURCE,
            rights=rights,
            paged=False,
            of_file=file_sha,
        ),
    )


def _checked(entry: ManualDocument) -> dict[str, str | None]:
    problems: dict[str, str] = {}
    values: dict[str, str | None] = {}

    def check(name: str, parse) -> None:
        try:
            values[name] = parse()
        except InvalidCorrection as error:
            problems[name] = str(error)

    check("document_id", lambda: validate_assigned_id(entry.document_id))
    check("citation", lambda: parse_correction("citation", entry.citation))
    check("title", lambda: parse_correction("title", entry.title))
    check("kind", lambda: parse_correction("kind", entry.kind))
    check("status", lambda: parse_correction("status", entry.status))
    check("language", lambda: _required(entry.language, "the language code, e.g. id or ar"))
    check("source_url", lambda: _url(entry.source_url))
    check("rights", lambda: _choice(entry.rights, tuple(r.value for r in Rights if r is not Rights.RESTRICTED)))
    check("reason", lambda: _required(entry.reason, "a reason: where the document came from, and why it is added"))
    for name in DATE_FIELDS:
        raw = getattr(entry, name)
        check(name, lambda name=name, raw=raw: parse_correction(name, raw) if raw.strip() else None)
    if not entry.file_bytes:
        problems["file"] = "choose the document's file (usually the official PDF)"
    if problems:
        raise InvalidManualDocument(problems)
    return values


def _required(raw: str, expected: str) -> str:
    if not raw.strip():
        raise InvalidCorrection(f"enter {expected}")
    return raw.strip()


def _url(raw: str) -> str:
    url = raw.strip()
    if not url.startswith(("https://", "http://")):
        raise InvalidCorrection("enter the address you got the document from, starting with https://")
    return url


def _choice(raw: str, choices: tuple[str, ...]) -> str:
    if raw not in choices:
        raise InvalidCorrection(f"choose one of {', '.join(choices)}")
    return raw
