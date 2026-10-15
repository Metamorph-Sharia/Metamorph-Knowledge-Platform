"""What amending and revoking links mean for the documents and articles they point at.

    revokes, supersedes       the target document is revoked
    partly_revokes            the document is partly revoked; a named article is revoked
    amends                    the document is amended; a named article is amended

Each change dates from when the changing document takes effect (its effective, promulgation or enactment
date, stated by a source or by its own text). An article changed or revoked loses its original wording
on the earliest such date: that is its `valid_to`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DOCUMENT_STATUS = {
    "revokes": "revoked",
    "supersedes": "revoked",
    "partly_revokes": "partly_revoked",
    "amends": "amended",
}
ARTICLE_STATUS = {"partly_revokes": "revoked", "amends": "amended"}
SOURCE = "links"  # registry.status_event.source for everything derived here


@dataclass(frozen=True)
class DatedLink:
    link_id: int
    type: str
    from_document: str
    to_document: str
    to_address: str | None
    effective_on: date | None  # when the changing document takes effect


@dataclass(frozen=True)
class StatusChange:
    document_id: str
    address: str | None  # None: the whole document
    status: str
    effective_from: date | None
    link_id: int


@dataclass(frozen=True)
class ProvisionExpiry:
    document_id: str
    address: str  # applies to the provisions under it too
    valid_to: date


def status_changes(links: list[DatedLink]) -> list[StatusChange]:
    changes = []
    for link in links:
        status = (ARTICLE_STATUS if link.to_address else DOCUMENT_STATUS).get(link.type)
        if status:
            changes.append(StatusChange(link.to_document, link.to_address, status, link.effective_on, link.link_id))
    return changes


def provision_expiries(links: list[DatedLink]) -> list[ProvisionExpiry]:
    earliest: dict[tuple[str, str], date] = {}
    for link in links:
        if link.type in ARTICLE_STATUS and link.to_address and link.effective_on:
            key = (link.to_document, link.to_address)
            earliest[key] = min(earliest.get(key, link.effective_on), link.effective_on)
    return [ProvisionExpiry(document, address, day) for (document, address), day in earliest.items()]
