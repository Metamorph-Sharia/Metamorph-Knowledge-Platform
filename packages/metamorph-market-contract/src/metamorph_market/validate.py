"""Every problem with a record: the JSON Schema's, then the rules a schema can't express."""

from __future__ import annotations

from metamorph_market.codec import to_dict
from metamorph_market.record import LicensedEntityRecord
from metamorph_market.schema import schema_problems


def problems(record: LicensedEntityRecord) -> list[str]:
    return schema_problems(to_dict(record)) + _cross_field_problems(record)


def _cross_field_problems(record: LicensedEntityRecord) -> list[str]:
    found = []
    entity = record.entity
    if not entity.id.startswith(f"{entity.register}:"):
        found.append(f"entity.id: {entity.id!r} is not on register {entity.register!r}")
    files = {file.sha256 for file in record.files}
    editions: set[str] = set()
    for index, listing in enumerate(record.listings):
        if listing.file not in files:
            found.append(f"listings[{index}].file: {listing.file[:12]}… is not in files")
        if listing.edition in editions:
            found.append(f"listings[{index}].edition: {listing.edition} is listed twice")
        editions.add(listing.edition)
    return found
