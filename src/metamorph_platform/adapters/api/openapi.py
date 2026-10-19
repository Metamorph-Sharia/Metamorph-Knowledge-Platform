"""The curation API's OpenAPI document: the contract the web app generates its TypeScript types from.

    uv run python -m metamorph_platform.adapters.api.openapi     # writes docs/api/openapi.json

The schema doesn't depend on any service, account or secret, so none is needed to produce it.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from metamorph_platform.adapters.api.accounts import Accounts
from metamorph_platform.adapters.api.app import create_api

COMMITTED = Path(__file__).resolve().parents[4] / "docs" / "api" / "openapi.json"


def openapi_document() -> dict[str, Any]:
    return create_api(lambda: nullcontext(), Accounts([]), secret="").openapi()


if __name__ == "__main__":
    COMMITTED.parent.mkdir(parents=True, exist_ok=True)
    COMMITTED.write_text(json.dumps(openapi_document(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {COMMITTED}")
