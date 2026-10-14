"""Metamorph contract v2: the normalized document every source connector emits, and its bundle.

The formal contract is the JSON Schemas in `schemas/`; these types mirror them exactly.
"""

from metamorph_contract.bundle import Bundle, BundleEntry, BundleWriter, Manifest, UnloadableBundle
from metamorph_contract.codec import ContractViolation, from_dict, from_json, to_dict, to_json
from metamorph_contract.document import (
    CONTRACT_VERSION,
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
from metamorph_contract.identity import KNOWN_ISSUERS, canonical_id, is_canonical, is_unresolved, unresolved_id
from metamorph_contract.paged_text import join_pages, page_marker, split_pages
from metamorph_contract.schema import DOCUMENT_SCHEMA, MANIFEST_SCHEMA, load_schema, schema_problems
from metamorph_contract.validate import problems

__all__ = [
    "CONTRACT_VERSION",
    "DOCUMENT_SCHEMA",
    "MANIFEST_SCHEMA",
    "KNOWN_ISSUERS",
    "Bundle",
    "BundleEntry",
    "BundleWriter",
    "Citation",
    "Confidence",
    "ContractViolation",
    "Dates",
    "DocumentInfo",
    "ExtractionMethod",
    "FileRef",
    "FileRole",
    "FoundIn",
    "Kind",
    "Manifest",
    "NormalizedDocument",
    "Provision",
    "Relation",
    "Rights",
    "SourceRef",
    "Status",
    "StatusClaim",
    "TextOrigin",
    "TextRef",
    "UnloadableBundle",
    "canonical_id",
    "from_dict",
    "from_json",
    "is_canonical",
    "is_unresolved",
    "join_pages",
    "load_schema",
    "page_marker",
    "problems",
    "schema_problems",
    "split_pages",
    "to_dict",
    "to_json",
    "unresolved_id",
]
