"""NormalizedDocument ⇄ JSON. Reading checks the JSON Schema first, so building can trust the shape."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from metamorph_contract.document import (
    Citation,
    Confidence,
    Dates,
    DocumentInfo,
    ExtractionMethod,
    FileRef,
    FileRole,
    FoundIn,
    Kind,
    NormalizedDocument,
    Provision,
    Relation,
    Rights,
    SourceRef,
    Status,
    StatusClaim,
    TextOrigin,
    TextRef,
)
from metamorph_contract.schema import schema_problems


class ContractViolation(Exception):
    """A document that doesn't meet contract v2. `problems` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def to_dict(document: NormalizedDocument) -> dict[str, Any]:
    return asdict(document)


def to_json(document: NormalizedDocument) -> str:
    return json.dumps(to_dict(document), ensure_ascii=False, allow_nan=False)


def from_json(line: str) -> NormalizedDocument:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractViolation([f"not JSON: {exc}"]) from None
    return from_dict(data)


def from_dict(data: Mapping[str, Any]) -> NormalizedDocument:
    found = schema_problems(data)
    if found:
        raise ContractViolation(found)
    return NormalizedDocument(
        contract_version=data["contract_version"],
        source=SourceRef(**data["source"]),
        document=_document_info(data["document"]),
        files=tuple(_file(file) for file in data["files"]),
        texts=tuple(_text(text) for text in data.get("texts", [])),
        provisions=tuple(Provision(**provision) for provision in data.get("provisions", [])),
        citations=tuple(_citation(citation) for citation in data.get("citations", [])),
        source_fields=data.get("source_fields", {}),
    )


def _document_info(info: Mapping[str, Any]) -> DocumentInfo:
    status = info["status"]
    return DocumentInfo(
        **{
            **info,
            "id_confidence": Confidence(info["id_confidence"]),
            "kind": Kind(info["kind"]),
            "status": StatusClaim(**{**status, "value": Status(status["value"])}),
            "dates": Dates(**info.get("dates", {})),
            "aliases": tuple(info.get("aliases", ())),
        }
    )


def _file(file: Mapping[str, Any]) -> FileRef:
    return FileRef(**{**file, "role": FileRole(file["role"]), "rights": Rights(file["rights"])})


def _text(text: Mapping[str, Any]) -> TextRef:
    return TextRef(
        **{
            **text,
            "origin": TextOrigin(text["origin"]),
            "method": ExtractionMethod(text["method"]),
            "rights": Rights(text["rights"]),
        }
    )


def _citation(citation: Mapping[str, Any]) -> Citation:
    return Citation(
        **{
            **citation,
            "relation": Relation(citation["relation"]),
            "found_in": FoundIn(citation["found_in"]),
            "confidence": Confidence(citation["confidence"]),
        }
    )
