# Market contract 1.0: the licensed entity

**Version 1.0 · 2026-10-27** · package `metamorph-market-contract` (module `metamorph_market`; Python ≥ 3.11; depends on `jsonschema`)

The market data layer's counterpart to [contract v2](../metamorph-contract/CONTRACT_V2.md). Contract v2 describes a legal document. This contract describes market records, one kind at a time, as each source arrives ([docs/market-data-layer-plan.md](../../docs/market-data-layer-plan.md)). Version 1.0 has one kind: **`licensed_entity`**, one license on a regulator's register.

**The formal contract is two JSON Schemas (draft 2020-12):**

| Schema | Describes |
|---|---|
| [`licensed-entity.schema.json`](src/metamorph_market/schemas/licensed-entity.schema.json) (`urn:metamorph:market:1.0:licensed-entity`) | One line of `records.jsonl` |
| [`market-manifest.schema.json`](src/metamorph_market/schemas/market-manifest.schema.json) (`urn:metamorph:market:1.0:manifest`) | `manifest.json` |

The Python types mirror them exactly, and a test fails on any drift.

## The rules

1. **One record per license.** Its ID is `{register}:{license key}`, e.g. `ojk:lpbbti:kep-49-d.05-2017` on register `ojk:lpbbti`. The key comes from the license number as printed, never from a URL or a row number.
2. **Report what the register says; don't interpret it.** Each edition that lists the license is one `listing`, with the row's cells under their printed headers. Whether a license left the register, and when, is the platform's to derive from the listings.
3. **Pointers, not payloads.** Each edition's file is a blob in the bundle, referenced by sha256. Every listing points at the edition it was read from, with its page and row number.
4. **Pass the register's own cells through** in `listings[].cells` and, for the newest listing, `source_fields`, beside the interpretation in `entity`.
5. **A bundle is a full snapshot.** Every license the connector has ever seen goes in each export, with all its listings.

## The record

```text
LicensedEntityRecord
  contract_version   "market-1.0"
  kind               "licensed_entity"
  source             connector, connector_version, source_id (the license number as printed), url, fetched_at
  entity             id, register, legal_name (newest), names (every other name listed),
                     business_type (sharia | conventional | unknown),
                     license (number, date, kind: license | registration | unknown),
                     website (as printed), channels (android | ios)
  listings[]         edition, file (sha256), page, row (as printed), legal_name (as listed then), cells
  files[]            sha256, role (register_edition), media_type, source_url, edition
  source_fields      the newest listing's cells, unchanged
```

`problems(record)` runs the schema and the rules that compare one value with another:
- the ID is on the record's register;
- every listing's file is in `files`;
- no edition is listed twice.

## Writing a bundle

```python
from metamorph_market import BundleWriter

with BundleWriter(out_dir, connector="ojk-register", connector_version="0.1.0", run_id=run_id) as bundle:
    sha = bundle.put_blob(edition_pdf)
    bundle.add(record)          # validated here: ContractViolation lists every problem
# the manifest is written only on a clean exit
```

```text
{bundle}/manifest.json           contract_version, connector, connector_version, run_id, created_at, records, blobs,
                                 complete, snapshot
{bundle}/records.jsonl           one record per line
{bundle}/blobs/{sha[:2]}/{sha}   every file referenced
```

A bundle without a manifest, or whose manifest names another contract, raises `UnloadableBundle` and is never loaded.
