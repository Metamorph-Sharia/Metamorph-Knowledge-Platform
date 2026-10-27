"""The JSON Schemas are the contract. The Python types must say exactly the same thing."""

from dataclasses import fields
from enum import StrEnum

import pytest
from jsonschema import Draft202012Validator
from metamorph_market import (
    MARKET_CONTRACT_VERSION,
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
from metamorph_market.schema import ENTITY_SCHEMA, MANIFEST_SCHEMA, load_schema

RECORD = load_schema(ENTITY_SCHEMA)
DEFINITIONS = RECORD["$defs"]

OBJECTS = {
    LicensedEntityRecord: RECORD,
    SourceRef: DEFINITIONS["source"],
    Entity: DEFINITIONS["entity"],
    License: DEFINITIONS["license"],
    Listing: DEFINITIONS["listing"],
    FileRef: DEFINITIONS["file"],
}

VOCABULARIES = {
    BusinessType: DEFINITIONS["entity"]["properties"]["business_type"],
    Channel: DEFINITIONS["entity"]["properties"]["channels"]["items"],
    FileRole: DEFINITIONS["file"]["properties"]["role"],
    LicenseKind: DEFINITIONS["license"]["properties"]["kind"],
}


@pytest.mark.parametrize("schema", [ENTITY_SCHEMA, MANIFEST_SCHEMA])
def test_each_schema_is_valid_json_schema(schema: str) -> None:
    Draft202012Validator.check_schema(load_schema(schema))


@pytest.mark.parametrize("dataclass_type", OBJECTS, ids=lambda t: t.__name__)
def test_each_type_has_exactly_the_schemas_properties(dataclass_type: type) -> None:
    schema = OBJECTS[dataclass_type]
    assert {f.name for f in fields(dataclass_type)} == set(schema["properties"])
    assert set(schema["required"]) == set(schema["properties"])  # every field is always written


@pytest.mark.parametrize("vocabulary", VOCABULARIES, ids=lambda t: t.__name__)
def test_each_vocabulary_matches_the_schema(vocabulary: type[StrEnum]) -> None:
    assert {member.value for member in vocabulary} == set(VOCABULARIES[vocabulary]["enum"])


def test_the_version_is_the_schemas() -> None:
    assert RECORD["properties"]["contract_version"]["const"] == MARKET_CONTRACT_VERSION
    assert load_schema(MANIFEST_SCHEMA)["properties"]["contract_version"]["const"] == MARKET_CONTRACT_VERSION
