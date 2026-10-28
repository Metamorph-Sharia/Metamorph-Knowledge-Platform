# Market contract 1.0: licensed entities, series and reports

**Version 1.0 · 2026-10-27** · package `metamorph-market-contract` (module `metamorph_market`; Python ≥ 3.11; depends on `jsonschema`)

The market data layer's counterpart to [contract v2](../metamorph-contract/CONTRACT_V2.md). Contract v2 describes a legal document. This contract describes market records, one kind at a time, as each source arrives ([docs/market-data-layer-plan.md](../../docs/market-data-layer-plan.md)). Version 1.0 has three kinds:
- **`licensed_entity`:** one license on a regulator's register;
- **`series`:** one statistic a regulator publishes, over time;
- **`report`:** a regulator's report, review, roadmap or masterplan, with its text as read (2026-10-28, Phase 4).

**The formal contract is four JSON Schemas (draft 2020-12):**

| Schema | Describes |
|---|---|
| [`licensed-entity.schema.json`](src/metamorph_market/schemas/licensed-entity.schema.json) (`urn:metamorph:market:1.0:licensed-entity`) | One line of `records.jsonl` |
| [`series.schema.json`](src/metamorph_market/schemas/series.schema.json) (`urn:metamorph:market:1.0:series`) | One line of `records.jsonl`, of kind `series` |
| [`report.schema.json`](src/metamorph_market/schemas/report.schema.json) (`urn:metamorph:market:1.0:report`) | One line of `records.jsonl`, of kind `report` |
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

## The series

```text
SeriesRecord
  contract_version   "market-1.0"
  kind               "series"
  source             connector, connector_version, source_id (the table, the measure and each member's key),
                     url (the page that shows it), fetched_at
  series             id {dataset}:{measure}:{dimension=key…}, dataset {issuer}:{source}:{table},
                     industry, group, metric, measure (each as the source names it),
                     dimensions[] (name, key, label): which slice of the table this is
  observations[]     period (YYYY-MM), value (as given, never rescaled), file (sha256 of the answer it came from)
  files[]            sha256, role (source_answer), media_type, source_url, edition (when the source last updated it)
  source_fields      what the source says of the series, unchanged
```

The same rules hold:
- **The key is the source's own.** A member's key, such as an account code, not its label or its row number. A label that changes keeps the series.
- **Report what the source says; don't interpret it.** A value is kept as given, in the source's units. Totals, shares and growth are the platform's to derive.
- **Pointers, not payloads.** Each answer is a blob, and every observation points at the one it was read from.
- **A bundle is a full snapshot** of every series the connector holds, unless its manifest says `snapshot: "datasets"`: then each dataset in it is whole, and a dataset not in it is untouched. A connector whose source is too large to re-send each week sends only the datasets that changed.

`problems(record)` checks a series' own rules:
- the ID is in the record's dataset;
- every observation's file is in `files`;
- every period has its series' frequency's form;
- no period is observed twice.

## The report

```text
ReportRecord
  contract_version   "market-1.0"
  kind               "report"
  source             connector, connector_version, source_id (the source's key, e.g. its page's name),
                     url (the page that lists it), fetched_at
  report             id {issuer}:{family}:{edition} or {issuer}:{family}:{year}:{name}
                     (ojk:lpksi:2025, ojk:roadmap:2023:rp3si), issuer, family, edition (as titled),
                     title, published_on (when known), language
  text               file (sha256 of the text: page by page, "<!-- page N -->" markers, as metamorph-pdf-text
                     wrote it), pages, method (text_layer | ocr), extraction (engine, engine_version, tier,
                     ocr_mode, pages_ocrd, pages_fallen_back)
  files[]            sha256, role (source_report), media_type, source_url, edition (published, or fetched)
  source_fields      what the source's page says of it, unchanged
```

- **A report has no legal force.** It says what a regulator reports or plans, never a rule.
- **The connector reads the PDF; the platform cuts the text** into chapters and passages. A better rule re-derives every report without reading a PDF again.
- **Both the PDF and the text are blobs**, referenced by sha256.

`problems(record)` checks that the ID names the report's issuer and family.

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
                                 complete, snapshot (full | datasets)
{bundle}/records.jsonl           one record per line
{bundle}/blobs/{sha[:2]}/{sha}   every file referenced
```

A bundle may hold records of both kinds. A bundle without a manifest, or whose manifest names another contract, raises `UnloadableBundle` and is never loaded.
