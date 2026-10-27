"""LicensedEntityRecord ⇄ JSON. Reading checks the JSON Schema first, so building can trust the shape."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from metamorph_market.record import (
    BusinessType,
    Channel,
    Entity,
    FileRef,
    FileRole,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    SourceRef,
)
from metamorph_market.schema import schema_problems


class ContractViolation(Exception):
    """A record that doesn't meet the market contract. `problems` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def to_dict(record: LicensedEntityRecord) -> dict[str, Any]:
    """The record as its JSON reads: tuples become arrays, so the schema sees what a loader will."""
    return json.loads(to_json(record))


def to_json(record: LicensedEntityRecord) -> str:
    return json.dumps(asdict(record), ensure_ascii=False, allow_nan=False)


def from_json(line: str) -> LicensedEntityRecord:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractViolation([f"not JSON: {exc}"]) from None
    return from_dict(data)


def from_dict(data: Mapping[str, Any]) -> LicensedEntityRecord:
    found = schema_problems(data)
    if found:
        raise ContractViolation(found)
    return LicensedEntityRecord(
        contract_version=data["contract_version"],
        kind=data["kind"],
        source=SourceRef(**data["source"]),
        entity=_entity(data["entity"]),
        listings=tuple(Listing(**listing) for listing in data["listings"]),
        files=tuple(FileRef(**{**file, "role": FileRole(file["role"])}) for file in data["files"]),
        source_fields=data["source_fields"],
    )


def _entity(entity: Mapping[str, Any]) -> Entity:
    return Entity(
        **{
            **entity,
            "names": tuple(entity["names"]),
            "business_type": BusinessType(entity["business_type"]),
            "license": License(**{**entity["license"], "kind": LicenseKind(entity["license"]["kind"])}),
            "channels": tuple(Channel(channel) for channel in entity["channels"]),
        }
    )
