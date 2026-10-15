"""The JSON Schemas in `schemas/` are the formal contract; this module applies them.

Anything outside Python (another language, a data catalog, a future integration) reads the
same files, so structure, vocabularies, patterns and formats are defined there and only there.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

DOCUMENT_SCHEMA = "normalized-document.schema.json"
MANIFEST_SCHEMA = "bundle-manifest.schema.json"


@cache
def load_schema(name: str) -> dict[str, Any]:
    return json.loads(files("metamorph_contract").joinpath("schemas", name).read_text(encoding="utf-8"))


def schema_problems(data: Any, schema: str = DOCUMENT_SCHEMA) -> list[str]:
    """Every way `data` breaks the schema, as "path: message", in document order."""
    errors = sorted(_validator(schema).iter_errors(data), key=lambda error: [str(p) for p in error.absolute_path])
    return [f"{_path(error)}: {_message(error)}" for error in errors]


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    # The format checker makes "date" and "date-time" binding, not just documentation.
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _message(error: ValidationError) -> str:
    """A failed anyOf/oneOf reports its own description: the default would print the whole instance."""
    description = error.schema.get("description") if isinstance(error.schema, dict) else None
    if error.validator not in {"anyOf", "oneOf"} or not description:
        return error.message
    is_small_value = isinstance(error.instance, str | int | float | bool) or error.instance is None
    return f"{error.instance!r} {description}" if is_small_value else description


def _path(error: ValidationError) -> str:
    parts = [f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path]
    return "".join(parts).lstrip(".") or "(document)"
