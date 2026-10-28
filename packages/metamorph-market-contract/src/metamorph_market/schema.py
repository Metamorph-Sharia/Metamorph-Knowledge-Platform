"""The JSON Schemas in `schemas/` are the formal contract; this module applies them."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

ENTITY_SCHEMA = "licensed-entity.schema.json"
SERIES_SCHEMA = "series.schema.json"
MANIFEST_SCHEMA = "market-manifest.schema.json"
RECORD_SCHEMAS = {"licensed_entity": ENTITY_SCHEMA, "series": SERIES_SCHEMA}  # by the record's kind


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads(files("metamorph_market").joinpath("schemas", name).read_text(encoding="utf-8"))


def record_problems(data: Any) -> list[str]:
    """A record's schema is its kind's; a record without a known kind has only that problem."""
    kind = data.get("kind") if isinstance(data, dict) else None
    if kind not in RECORD_SCHEMAS:
        return [f"kind: {kind!r} is not one of {sorted(RECORD_SCHEMAS)}"]
    return schema_problems(data, RECORD_SCHEMAS[kind])


def schema_problems(data: Any, schema: str = ENTITY_SCHEMA) -> list[str]:
    """Every way `data` breaks the schema, as "path: message", in record order."""
    errors = sorted(_validator(schema).iter_errors(data), key=lambda error: [str(p) for p in error.absolute_path])
    return [f"{_path(error)}: {error.message}" for error in errors]


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    # The format checker makes "date" and "date-time" binding, not just documentation.
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _path(error: ValidationError) -> str:
    parts = [f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path]
    return "".join(parts).lstrip(".") or "(record)"
