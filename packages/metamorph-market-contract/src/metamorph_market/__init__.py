"""Market contract 1.0: what a Metamorph market connector emits (MARKET_CONTRACT.md)."""

from metamorph_market.bundle import Bundle, BundleEntry, BundleWriter, Manifest, UnloadableBundle
from metamorph_market.codec import ContractViolation, from_dict, from_json, to_dict, to_json
from metamorph_market.record import (
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
from metamorph_market.validate import problems

__all__ = [
    "MARKET_CONTRACT_VERSION",
    "Bundle",
    "BundleEntry",
    "BundleWriter",
    "BusinessType",
    "Channel",
    "ContractViolation",
    "Entity",
    "FileRef",
    "FileRole",
    "License",
    "LicensedEntityRecord",
    "LicenseKind",
    "Listing",
    "Manifest",
    "SourceRef",
    "UnloadableBundle",
    "from_dict",
    "from_json",
    "problems",
    "to_dict",
    "to_json",
]
