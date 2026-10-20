"""The curation API's contract: the OpenAPI document the web app generates its types from, committed."""

from __future__ import annotations

import json

from metamorph_platform.adapters.api.openapi import COMMITTED, openapi_document


def test_the_committed_openapi_document_is_the_apis() -> None:
    """If this fails, the API changed: regenerate with `uv run python -m metamorph_platform.adapters.api.openapi`,
    and tell the web app (it regenerates its types from this file)."""
    assert json.loads(COMMITTED.read_text()) == openapi_document()


def test_every_curation_capability_is_in_the_contract() -> None:
    """The design's tables (docs/curation-web-separation-design.md): 9 reads, 14 actions, and signing in."""
    operations = [(method, path) for path, item in openapi_document()["paths"].items() for method in item]

    assert sum(method == "get" for method, _ in operations) == 12
    assert sum(method == "post" for method, _ in operations) == 15
    assert ("post", "/api/v1/documents/{document_id}/texts/{text_sha256}/correction") in operations
