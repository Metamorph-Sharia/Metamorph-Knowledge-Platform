"""The JSON Schemas are the contract. The Python types must say exactly the same thing."""

from dataclasses import fields
from enum import StrEnum

import pytest
from jsonschema import Draft202012Validator
from metamorph_market import (
    MARKET_CONTRACT_VERSION,
    BusinessType,
    Channel,
    Dimension,
    Entity,
    FileRef,
    FileRole,
    Frequency,
    License,
    LicensedEntityRecord,
    LicenseKind,
    Listing,
    Observation,
    Series,
    SeriesRecord,
    SourceRef,
)
from metamorph_market.schema import ENTITY_SCHEMA, MANIFEST_SCHEMA, SERIES_SCHEMA, load_schema

RECORD = load_schema(ENTITY_SCHEMA)
DEFINITIONS = RECORD["$defs"]
SERIES = load_schema(SERIES_SCHEMA)
SERIES_DEFINITIONS = SERIES["$defs"]

OBJECTS = {
    LicensedEntityRecord: RECORD,
    SourceRef: DEFINITIONS["source"],
    Entity: DEFINITIONS["entity"],
    License: DEFINITIONS["license"],
    Listing: DEFINITIONS["listing"],
    FileRef: DEFINITIONS["file"],
    SeriesRecord: SERIES,
    Series: SERIES_DEFINITIONS["series"],
    Dimension: SERIES_DEFINITIONS["dimension"],
    Observation: SERIES_DEFINITIONS["observation"],
}

SHARED = ("source", "file")  # one type each, so both schemas must define them alike, apart from the file roles

VOCABULARIES = {
    BusinessType: DEFINITIONS["entity"]["properties"]["business_type"],
    Channel: DEFINITIONS["entity"]["properties"]["channels"]["items"],
    LicenseKind: DEFINITIONS["license"]["properties"]["kind"],
    Frequency: SERIES_DEFINITIONS["series"]["properties"]["frequency"],
}


@pytest.mark.parametrize("schema", [ENTITY_SCHEMA, SERIES_SCHEMA, MANIFEST_SCHEMA])
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


def test_each_kinds_file_roles_are_file_roles() -> None:
    roles = [schema["$defs"]["file"]["properties"]["role"]["enum"] for schema in (RECORD, SERIES)]
    assert {member.value for member in FileRole} == {role for kind in roles for role in kind}


@pytest.mark.parametrize("name", SHARED)
def test_both_kinds_define_the_shared_types_alike(name: str) -> None:
    def without_roles(definition: dict) -> dict:
        return {**definition, "properties": {k: v for k, v in definition["properties"].items() if k != "role"}}

    assert set(DEFINITIONS[name]["properties"]) == set(SERIES_DEFINITIONS[name]["properties"])
    assert without_roles(DEFINITIONS[name])["required"] == without_roles(SERIES_DEFINITIONS[name])["required"]


def test_the_version_is_the_schemas() -> None:
    assert RECORD["properties"]["contract_version"]["const"] == MARKET_CONTRACT_VERSION
    assert SERIES["properties"]["contract_version"]["const"] == MARKET_CONTRACT_VERSION
    assert load_schema(MANIFEST_SCHEMA)["properties"]["contract_version"]["const"] == MARKET_CONTRACT_VERSION
