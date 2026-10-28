"""Market records ⇄ JSON. Reading checks the record's JSON Schema first, so building can trust the shape."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from metamorph_market.record import (
    BusinessType,
    Channel,
    Dimension,
    Entity,
    Extraction,
    FileRef,
    FileRole,
    Frequency,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    MarketRecord,
    Observation,
    Report,
    ReportRecord,
    ReportText,
    Series,
    SeriesRecord,
    SourceRef,
    TextMethod,
)
from metamorph_market.schema import record_problems


class ContractViolation(Exception):
    """A record that doesn't meet the market contract. `problems` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def to_dict(record: MarketRecord) -> dict[str, Any]:
    """The record as its JSON reads: tuples become arrays, so the schema sees what a loader will."""
    return json.loads(to_json(record))


def to_json(record: MarketRecord) -> str:
    return json.dumps(asdict(record), ensure_ascii=False, allow_nan=False)


def from_json(line: str) -> MarketRecord:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractViolation([f"not JSON: {exc}"]) from None
    return from_dict(data)


def from_dict(data: Mapping[str, Any]) -> MarketRecord:
    found = record_problems(data)
    if found:
        raise ContractViolation(found)
    if data["kind"] == "series":
        return _series_record(data)
    if data["kind"] == "report":
        return _report_record(data)
    return LicensedEntityRecord(
        contract_version=data["contract_version"],
        kind=data["kind"],
        source=SourceRef(**data["source"]),
        entity=_entity(data["entity"]),
        listings=tuple(Listing(**listing) for listing in data["listings"]),
        files=_files(data),
        source_fields=data["source_fields"],
    )


def _series_record(data: Mapping[str, Any]) -> SeriesRecord:
    series = data["series"]
    return SeriesRecord(
        contract_version=data["contract_version"],
        kind=data["kind"],
        source=SourceRef(**data["source"]),
        series=Series(
            **{
                **series,
                "dimensions": tuple(Dimension(**member) for member in series["dimensions"]),
                "frequency": Frequency(series["frequency"]),
            }
        ),
        observations=tuple(Observation(**observation) for observation in data["observations"]),
        files=_files(data),
        source_fields=data["source_fields"],
    )


def _report_record(data: Mapping[str, Any]) -> ReportRecord:
    text = data["text"]
    return ReportRecord(
        contract_version=data["contract_version"],
        kind=data["kind"],
        source=SourceRef(**data["source"]),
        report=Report(**data["report"]),
        text=ReportText(
            **{**text, "method": TextMethod(text["method"]), "extraction": Extraction(**text["extraction"])}
        ),
        files=_files(data),
        source_fields=data["source_fields"],
    )


def _files(data: Mapping[str, Any]) -> tuple[FileRef, ...]:
    return tuple(FileRef(**{**file, "role": FileRole(file["role"])}) for file in data["files"])


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
