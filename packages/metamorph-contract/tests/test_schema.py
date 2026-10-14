"""The JSON Schemas are the contract. The Python types must say exactly the same thing."""

import re
from dataclasses import MISSING, fields
from enum import StrEnum

import pytest
from jsonschema import Draft202012Validator
from metamorph_contract import (
    KNOWN_ISSUERS,
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
from metamorph_contract.schema import DOCUMENT_SCHEMA, MANIFEST_SCHEMA, load_schema

DOCUMENT = load_schema(DOCUMENT_SCHEMA)
DEFINITIONS = DOCUMENT["$defs"]

OBJECTS = {
    NormalizedDocument: DOCUMENT,
    SourceRef: DEFINITIONS["source"],
    DocumentInfo: DEFINITIONS["documentInfo"],
    StatusClaim: DEFINITIONS["statusClaim"],
    Dates: DEFINITIONS["dates"],
    FileRef: DEFINITIONS["file"],
    TextRef: DEFINITIONS["text"],
    Provision: DEFINITIONS["provision"],
    Citation: DEFINITIONS["citation"],
}

VOCABULARIES = {
    Kind: DEFINITIONS["documentInfo"]["properties"]["kind"],
    Status: DEFINITIONS["statusClaim"]["properties"]["value"],
    Confidence: DEFINITIONS["confidence"],
    FileRole: DEFINITIONS["file"]["properties"]["role"],
    TextOrigin: DEFINITIONS["text"]["properties"]["origin"],
    ExtractionMethod: DEFINITIONS["text"]["properties"]["method"],
    Relation: DEFINITIONS["citation"]["properties"]["relation"],
    FoundIn: DEFINITIONS["citation"]["properties"]["found_in"],
}


@pytest.mark.parametrize("schema", [DOCUMENT_SCHEMA, MANIFEST_SCHEMA])
def test_schemas_are_valid_draft_2020_12(schema) -> None:
    Draft202012Validator.check_schema(load_schema(schema))


@pytest.mark.parametrize(("type_", "schema"), OBJECTS.items(), ids=lambda value: getattr(value, "__name__", ""))
def test_each_type_has_exactly_the_schema_properties(type_, schema) -> None:
    assert {f.name for f in fields(type_)} == set(schema["properties"])


@pytest.mark.parametrize(("type_", "schema"), OBJECTS.items(), ids=lambda value: getattr(value, "__name__", ""))
def test_every_field_python_cannot_default_is_required_in_json(type_, schema) -> None:
    """Python always writes every field, so the schema may require more (e.g. contract_version), never fewer."""
    without_default = {f.name for f in fields(type_) if f.default is MISSING and f.default_factory is MISSING}
    assert without_default <= set(schema.get("required", []))


@pytest.mark.parametrize(
    ("vocabulary", "schema"), VOCABULARIES.items(), ids=lambda value: getattr(value, "__name__", "")
)
def test_each_vocabulary_matches_its_schema_enum(vocabulary: type[StrEnum], schema) -> None:
    assert [member.value for member in vocabulary] == schema["enum"]


def test_restricted_rights_exist_in_python_but_are_not_bundleable() -> None:
    assert [r.value for r in Rights if r is not Rights.RESTRICTED] == DEFINITIONS["rights"]["enum"]


def test_the_canonical_id_pattern_names_exactly_the_known_issuers() -> None:
    issuers = re.match(r"\^\(\?:([a-z|]+)\)", DEFINITIONS["canonicalId"]["pattern"])[1].split("|")
    assert set(issuers) == KNOWN_ISSUERS == set(DEFINITIONS["issuer"]["enum"])
