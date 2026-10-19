# Plan: Data / Source Management layer → a consumable PostgreSQL

## Context

Four connector repos (OJK, BPK, BI, DSN-MUI) each collect one issuer's documents. They share team interface v1.0 (byte-identical copies), but each keeps its results in its own store and shape:
- OJK and BPK: SQLite + `data/corpus/`.
- DSN-MUI: SQLite + JSONL.
- BI: its own PostgreSQL.

Interface v1.0 moves raw files only. The meaning (canonical IDs, status, relations, provisions, cleaned text) lives outside it.

The analysis in `OJK-Source-Connector/docs/research/platform-architecture.md` led to decisions P1–P7, all approved by the user:
- A shared contract v2.
- Issuer-namespaced IDs.
- Vector and graph in Postgres, kept for the next layer.
- Curation as overlays.
- Connectors run as containers under Airflow.
- Stage A (each connector exports from its own pipeline) before Stage B.
- A new platform repo.

User choices for this plan:
- Local Docker Compose first.
- A small web app for curation.
- I implement the changes in all four connector repos.

**Outcome:** a PostgreSQL `published` schema, filled automatically from all four connectors and corrected by the Metamorph team. It is a documented, stable read contract that the Knowledge and Retrieval layer consumes. **Out of scope:** chunking, embeddings, search index, retrieval API, chatbot.

## Architecture (Clean Architecture, applied where it pays)

New repo **`/Users/biru/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform`** (uv workspace):

```
packages/metamorph-contract/      stdlib-only, imported by every connector (pinned git tag)
  metamorph_contract/document.py   NormalizedDocument + Source/Document/FileRef/TextRef/Provision/Citation dataclasses
  metamorph_contract/schema.json   JSON Schema (contract_version "2.0")
  metamorph_contract/validate.py   validate(doc) -> list[str]
  metamorph_contract/bundle.py     BundleWriter: manifest.json + documents.jsonl + blobs/{sha[:2]}/{sha}
  metamorph_contract/text.py       paged-text convention: "=== page N ===" lines (DSN-MUI's existing format)
src/metamorph_platform/
  domain/        pure, stdlib only
    identity.py    issuer namespaces, CanonicalId, alias normalization, citation text → id candidates
    merge.py       field precedence across sources; overlay of curation onto source values; conflict detection
    structure/     shared Indonesian legal parser: peraturan (UU 12/2011 format: POJK/PADK/PBI/PADG/UU/PP),
                   surat_edaran (SEOJK/SEBI), lampiran, fatwa; page-break repair; quality checks
    citations.py   text-derived citations: Mengingat, revocation clauses, "dalam rangka pelaksanaan Pasal …",
                   "Fatwa DSN-MUI Nomor …"
    validity.py    status timeline + provision valid_from/valid_to from links
  application/
    ports.py       BundleSource, BlobStore, RegistryRepository, CurationRepository, IngestLedger, Clock
    use_cases/     load_bundle · resolve_citations · parse_structure · compute_validity · publish ·
                   curate (verify, correct, assign_id, suppress, link_citation, add_manual, resolve_conflict) ·
                   review_queues · health
  adapters/
    postgres/      psycopg3 repositories + migrations/ (numbered plain-SQL files, tiny runner)
    blobs/         s3.py (any S3 API via boto3: SeaweedFS locally, cloud S3/GCS later), local.py (tests and dev)
    bundles/       local-directory reader
    web/           FastAPI + Jinja2 server-rendered curation app (calls curate/review use cases only);
                   retired 2026-10-19 for Metamorph-Curation-Web over adapters/api (curation-web-separation-design.md)
  wiring.py        the single composition root
  cli.py           `platform db migrate | load <bundle> | resolve | parse | validity | publish | health | web`
dags/              Airflow DAG files (framework layer; they call containers and the CLI only)
docker/            compose.yml, platform.Dockerfile
tests/test_architecture.py   dependency rule, copied and adapted from BPK-Source-Connector/tests/test_architecture.py
```

Clean-architecture rules (from the skill review, matching BPK's practice):
- **Dependencies point inward only.** `domain` imports nothing outside the standard library. `application` imports only `domain`. Only `adapters` and the entry points import psycopg, boto3, FastAPI or Airflow. The `test_architecture.py` pattern enforces this.
- **Ports exist only where a second implementation exists.** Every port has an in-memory fake in tests; `BlobStore` and `BundleSource` also have two real implementations. The parser, citation extractor and merge rules are plain functions, not interfaces. No DI framework: constructor injection in `wiring.py`.
- **DTOs cross boundaries.** Bundles arrive as `NormalizedDocument` dataclasses. Repositories return domain objects, never DB rows. Web views get view-model dicts.
- **One use case per module** (single responsibility), unlike OJK's monolithic `pipeline.py`.
- **The knowledge layer depends only on the `published` schema**, the outermost read contract. It never reads `registry` or `curation` tables.

## PostgreSQL (one cluster, four schemas plus `platform_meta` for migrations; Postgres 16 with `pgvector` installed but unused here)

| Schema | Written by | Main tables |
|---|---|---|
| `ingest` | loader, Airflow tasks | `run`, `bundle` (connector, run_id, uri, manifest, package hash, result), `quarantine` (invalid docs with errors), `event`, `health_snapshot` |
| `registry` | loader + resolver/parser/validity only | `document` (canonical id PK, issuer, family, number, year, citation, title, kind, dates, status, id_confidence, missing_since), `document_source` ((connector, source_id) PK, source_fields jsonb, package_hash, first/last seen), `alias`, `file` + `document_file` (role, rights), `text_version` (sha, origin, method, language, paged, rights, is_current), `provision` (address PK, parent, kind, label, heading, char/page span, parser_version, quality), `citation` (raw claims with evidence), `link` (type, from/to document + provision, effective_on, method, confidence), `status_event` |
| `curation` | web app use cases only | `override` (target, field, value, reason, author, active), `suppression`, `review_item` (unresolved_id, quarantine, conflict, unresolved_citation, structure_suspect), `conflict`, `audit_log`, `user` |
| `published` | `publish` use case only | `document`, `document_source`, `file`, `text`, `provision`, `link`, `status_event`, `change_log` (document_id, changed_at, change) |

Notes:
- **`published` holds the effective values:** registry values with active overrides applied (`domain/merge.py`), suppressions removed, and only `rights ∈ {public, licensed}`. It is rebuilt per changed document, so the knowledge layer can index incrementally from `change_log`. Documented in `docs/published-schema.md`.
- **Link vocabulary:** `amends`, `revokes`, `partly_revokes`, `supersedes`, `implements`, `legal_basis`, `adopts_fatwa`, `changes_fatwa`, `refers_to`.
- **IDs:**
  - OJK: `ojk:{pojk|seojk|padk}:{year}:{n}`
  - BI: `bi:{pbi|padg|sebi}:{year}:{n}`
  - DSN-MUI fatwas: `dsnmui:fatwa:{n}`; pedoman and ta'limat formats are fixed from DSN's parser in Phase 1
  - National laws via BPK: `id:{uu|pp|perpres|pmk|…}:{year}:{n}`
  - Unresolved: `unresolved:{connector}:{source_id}`, routed to curation.

**`load_bundle` semantics:**
1. Validate each document. If invalid → `ingest.quarantine` and a review item; never half-load.
2. Idempotent by package hash per (connector, source_id).
3. A new text sha creates a new `text_version`; old versions are kept.
4. Never overwrite an overridden field. If the source value changed underneath an override → `conflict`.
5. Documents absent from a complete snapshot → `missing_since`.
6. One transaction per document.

## Bundle (Stage A transport)

Each connector's new `export --format v2 --out DIR` writes a **full snapshot** bundle:
- `manifest.json`: contract_version, connector, connector_version, run_id, counts, `complete`.
- `documents.jsonl`.
- `blobs/`: content-addressed, holding official files and paged UTF-8 texts.

Texts travel as blobs (pointers, not payloads). Restricted texts (RegAlert English, BPK abstracts) are never bundled. A platform task uploads new blobs to the object store (skipping existing shas), then runs `load_bundle`. **Connectors stay free of S3, Postgres and Airflow.**

## Phases

**Phase 0 — BI compliance fixes** (`BI-Source-Connector`).
- Fixes:
  - Remove `verify=False` (`src/connectors/bi_source.py`).
  - Identifying User-Agent instead of the Chrome string.
  - `discover(None)` pages to the end instead of stopping at `max_pages`.
  - `version` from file ETag/Last-Modified, not the URL slug.
  - `fetch` raises `ItemFailed` when the main PDF fails.
  - Update the README claim about bypassing F5.
- **Note:** BI's `AGENTS.md` asks agents not to edit code automatically and to work in mentor mode. Confirm with the BI owner before changing that repo; if they object, deliver these changes as patches for them to apply.
- Exit: BI's tests pass, and a live `discover(None)` lists the whole site.

**Phase 1 — Contract v2 package.**
- `packages/metamorph-contract` with dataclasses, JSON Schema, validator, `BundleWriter` and docs (`CONTRACT_V2.md`).
- Interface v1.0 stays unchanged; `normalize()` comes in Stage B.
- Gate: the four repo owners review the contract doc.
- Exit: schema tests pass, and an example bundle validates.

**Phase 2 — Platform skeleton.**
- Repo, uv workspace, ruff, pytest, `test_architecture.py`.
- `compose.yaml`: `pgvector/pgvector:pg16`, SeaweedFS (S3-compatible; MinIO no longer publishes community images), Airflow 2.10 (LocalExecutor, its own metadata database), and the platform image as a one-shot `migrate` job. The web app joins in Phase 7.
- Migrations for the four schemas; `metamorph db migrate | status`.
- **Done 2026-10-14.**
- Exit: `docker compose up` gives healthy services, and migrations apply from scratch.

**Phase 3 — OJK reference export + loader + publish (one source, end to end).**
- OJK: `src/ojk_connector/export_v2.py`.
  - A pure mapping (store DTO → `NormalizedDocument`) that reuses `identity.CanonicalId`, aliases, `standing` → status, and RegAlert lineage → citations.
  - Bundle only public texts.
  - CLI verb `export --format v2` in `cli.py`.
  - Keep the concrete `Store` out of the mapping (BPK review gap 4).
- Platform: `load_bundle`, `publish`, the Postgres repositories, `blobs/s3.py`.
- Exit: all OJK documents (973 today, from `data/corpus/`) in `published`; reloading the same bundle changes nothing; one document with `id_confidence = none` sits in the review queue.
- **Done 2026-10-15:** 973 loaded and published in ~10 s; a fresh export reloads as 973 unchanged with nothing republished; 1 unresolved document in the review queue; all 1,436 citations name a target (906 point to national laws that BPK will load in Phase 4).

**Phase 4 — BPK, DSN-MUI, BI exports.**
- **BPK:**
  - New use case `application/use_cases/export_v2.py` behind a new `BundleWriter` port, with the adapter `adapters/storage/v2_bundle.py`.
  - A pure `domain/identity.py`: form, number and year → `id:{form}:{year}:{n}`; BPK record IDs become aliases and source IDs.
  - Relations → citations (with `target_id` when the target is a held record); status and `in_force` → status; files and paged texts → blobs.
  - Its `test_architecture.py` must still pass.
- **DSN-MUI:**
  - `dsn_ingest/export_v2.py` and a CLI verb in `__main__.py`.
  - Latin text (`self_extracted`) and Arabic OCR (`language=ar`, `origin=ocr`) as separate texts.
  - Kinds `fatwa` / `guideline` / `circular`.
  - Ta'limat → `changes_fatwa` and pedoman → `implements` citations, from fatwa numbers in titles.
  - Fix the absolute `raw_path` (needed in containers).
- **BI:**
  - `src/pipeline/exporter_v2.py` reads BI's private Postgres.
  - Pages → one paged text blob; `legal_provisions` → `provisions[]`, kept as a cross-check.
  - IDs `bi:{type}:{year}:{n}`.
  - BI's database stays private to BI.
- Exit: every connector's bundle validates in its own CI (a contract test using `metamorph_contract.validate`), and all four are loaded and published.
- **Done 2026-10-15:** all four bundles load and publish: 2,524 documents and 3,976 texts (164 of them Arabic). A fresh export of each reloads as all unchanged, and the database rebuilds from the four bundles in about 30 s. 661 of OJK's 906 citations to national laws now name a document BPK supplied. Each repo tests that its exported entries pass the contract.
  - **BPK:** as planned. `source_id` is `bpk:{record_id}`, the interface connector's key. Citations come from the outgoing labels only; the incoming ones (`Diubah dengan` …) set the status. 130 documents, 453 citations, all with a target.
  - **DSN-MUI:** fatwas only, 164 of them. 2 have broken links at the source, so they have no content. The store holds no pedoman or ta'limat (`sync` stores fatwas only), so `changes_fatwa` and `implements` wait until those products are stored. Paths are now relative to `data/dsn/`, and old absolute paths are converted when the store opens.
  - **BI:**
    - **Input:** the export reads BI's processed JSON (one file per regulation, written from BI's database by every ingest), not the database. That keeps the database private and needs no running BI Postgres.
    - **IDs:** taken from the title, because BI's `regulation_number` and `regulation_year` fields are unreliable.
    - **Overwritten files:** 38 PDFs were overwritten on disk by BI's old file naming, and some had their pages extracted from the replacement. They are left out and listed in `lost_files` for a re-fetch. The naming is now content-addressed.
    - **Provisions:** `legal_provisions` travel as a summary in `source_fields`, not as contract provisions. Their text is cut at 1,000 characters and starts a few characters late, so their offsets can't be trusted. The Phase 5 parser produces provisions for every source.

**Phase 5 — Resolver, structure parser, validity.**
- `domain/structure/` grammars, seeded from BI's regexes (`BI-Source-Connector/src/pipeline/extractor.py:155-177`) and the anatomy findings (`OJK-Source-Connector/docs/research/ojk-publishing-and-storage/02-document-anatomy.md`).
  - Addresses like `pasal-115/ayat-1/huruf-a`, `penjelasan/pasal-115`, `lampiran-i/bab-ii`.
  - Repair page breaks; skip tables of contents.
  - Quality checks: Pasal continuity, Penjelasan ⊆ body, ayat continuity → `structure_suspect` review items.
- `domain/citations.py`: text-derived citations.
- `resolve_citations`: alias → link; unresolved citations stay queued and resolve when their target later loads.
- `compute_validity`: status timeline, plus provision `valid_to` from `partly_revokes` and `amends` links.
- Exit:
  - ≥ 95% of POJK and PBI texts pass the structure checks.
  - Mengingat citations to held documents resolve at ≥ 90%.
  - The fatwa links from sharia regulations (e.g. POJK 10/POJK.05/2019) appear as `adopts_fatwa`.
- **Done 2026-10-15:** `metamorph build` (parse → resolve → validity → publish) takes about 50 s over the whole corpus, and a second run changes nothing.
  - **Structure:** 2,554 texts give 280,555 provisions. 96.5% of POJK and 96.3% of PBI texts pass every check. The 212 texts that don't are queued as `structure_suspect`: captured web pages, BI summaries, text lost at page breaks, and OCR'd national laws.
  - **Citations:** all 2,185 Mengingat citations to held documents are linked. Against RegAlert's independent lineage, the text finds 99.7% of the legal basis of documents that have a Mengingat. SEOJKs have none: what RegAlert calls their legal basis is the POJK they `implements`.
  - **Fatwa links:** 255 `adopts_fatwa` links run from 10 documents to 87 fatwas. POJK 10/POJK.05/2019, the plan's example, cites fatwas only generically ("fatwa DSN-MUI"), never by number, so it has none.
  - **Links and validity:** 6,265 citations linked; 3,745 wait for documents not held yet, and 4 name nothing (`unresolved_citation`). 2,493 status events and 1,127 article end dates follow from them.
  - **Added beyond the plan:**
    - Dates stated in the text (`domain/dates.py`). OJK and BI send none, and validity needs them.
    - An `unknown` status takes the status links imply: 499 BI regulations gained one.
    - `docs/published-schema.md`.

**Phase 6 — Airflow (Stage A).**
- One Dockerfile per connector repo:
  - OJK: uv.
  - BPK: tesseract, ghostscript, `ind` language data.
  - DSN-MUI: tesseract `ara`.
  - BI: Python 3.13, tesseract.
- Named volumes hold each connector's `data/` and OJK's RegAlert token. The one-time `auth login` is documented.
- DAGs `ingest_{ojk,bpk,bi,dsn_fatwa,dsn_pedoman,dsn_talimat}`:
  1. `DockerOperator`: `run; rc=$?; export --format v2; exit rc`. A bundle is still produced when `run` raises alerts.
  2. Upload blobs and `load_bundle` (`trigger_rule=all_done`, and only if the manifest is `complete`).
  3. Outlet Dataset `registry`.
- DAG `registry_build`, triggered by that Dataset: resolve → parse → validity → publish → health.
- Schedules: OJK, BPK and BI daily; DSN-MUI weekly, plus a monthly full pass.
- Failures alert via Airflow callbacks and `ingest.health_snapshot`.
- Exit: 7 consecutive days of unattended runs; a new document reaches `published` within 24 hours.
- **Done 2026-10-15, with the 7-day exit still open:** the DAGs ship paused, so the clock starts when they are unpaused.
  - **Built:**
    - A Dockerfile per connector repo, built from the workspace root with a per-Dockerfile ignore file.
    - Every task runs as a container on the `metamorph` network (`dags/metamorph_pipeline/containers.py`).
    - The jobs are plain data, tested without Airflow (`jobs.py`, `tests/test_dag_jobs.py`).
    - `registry_build` runs on the `metamorph://registry` Dataset, plus a daily `health` DAG.
    - `metamorph health` writes to `ingest.health_snapshot` (migration 0007).
    - Failure alerts go to the task log and an optional webhook.
  - **Verified with `airflow dags test`:**
    - **DSN-MUI:** 26 s; a live crawl, nothing new.
    - **BPK:** 7 min.
    - **BI:** 3 min; its first run filled BI's own database with the 25 newest regulations.
    - **registry_build:** health ok.
    - **OJK:** RegAlert answered HTTP 403 (access refused; sign-in still works). The run failed and alerted, and still exported and loaded its snapshot, as designed.
  - **Fixes the runs exposed:**
    - OJK kept checking about 900 documents after the first 403. It now stops at the first refusal and raises one critical `access_forbidden` alert.
    - BPK re-saved judicial-review files that BPK resends without an ETag, so 16 documents looked changed every day. Identical bytes now keep their first fetch time.
  - **Changed from the plan:**
    - Each connector's `data/` is bind-mounted from its repository instead of a named volume, so scheduled and manual runs share one store and the existing data stays where it is.
    - DSN-MUI pedoman and ta'limat DAGs wait until `sync` stores those products.
    - BI's database is `bi` in the platform's PostgreSQL, with its own role.

**Phase 7 — Curation web app.**
- FastAPI + Jinja2; HTTP basic auth with team accounts from environment variables (local phase), so every action records its author.
- Pages: a health dashboard, review queues (unresolved IDs, quarantine, conflicts, unresolved citations, structure suspects), and a document view (effective values versus each source, files via presigned object-store URLs, provision tree, links in and out).
- Actions: verify, correct a field, assign a canonical ID, suppress, link a citation by hand, resolve a conflict, and add a manual document. A manual document is an upload plus a form that builds a `connector=manual` bundle and goes through `load_bundle`, so there is one write path.
- Exit: every queue is actionable; overrides survive reloads; a source change under an override raises a conflict; everything is in `audit_log`.
- **Done 2026-10-15:** every exit criterion is covered by a test against PostgreSQL. The pages work against the real registry: the Overview loads in about 0.13 s, a document page in about 0.04 s.
  - **Built:**
    - `domain/curation.py`: correction parsing, conflicts and ID rules. `domain/manual.py`: manual documents, with every bad field reported.
    - `application/curate.py`, `add_manual_document.py` and `views.py` (the read models).
    - Adapters: `adapters/postgres/curation.py` and `views.py`, and `adapters/web` (FastAPI + Jinja2, server-rendered, little JavaScript).
    - Migration 0008: `ON UPDATE CASCADE` on the document foreign keys, `curation.id_assignment`, `audit_log.reason`, and one open conflict per correction.
    - `metamorph web` and `metamorph curator hash-password`, and a compose `web` service.
  - **The loader now applies curation:** a curator's assigned ID applies on every later load, and a source change under a correction raises a conflict.
  - **Changed from the plan:**
    - Files and texts are streamed through the app, behind sign-in, instead of presigned object-store URLs. The object store stays private.
    - A manual document may not reuse an ID a connector holds. It would overwrite the connector's values; attaching files to existing documents is a later feature.
    - Assigning an ID that already exists is refused: a duplicate is suppressed instead.
  - **Interface quality:** built to Vercel's Web Interface Guidelines, and reviewed against them. Checked in screenshots in light, dark and mobile. The taste skill's landing-page rules don't apply to an admin tool; its contrast, states, one-accent, one-radius and no-em-dash rules do.

Phases 6 and 7 can run in parallel after Phase 5. (Stage B — interface v2 `normalize()` with Airflow driving discover/fetch/normalize — follows this plan and isn't part of it.)

## Critical files

- **New:** `Metamorph-Knowledge-Platform/` (everything above); `docs/published-schema.md` (the consumer contract).
- **OJK:** `src/ojk_connector/export_v2.py` (new), `cli.py`, `Dockerfile` (new); reuse `identity.py` (`CanonicalId`, `resolve_id_from_text`, `assess_text`) and `export.py` (row → entry helpers).
- **BPK:** `application/use_cases/export_v2.py`, `application/ports.py` (`BundleWriter`), `adapters/storage/v2_bundle.py`, `domain/identity.py`, `wiring.py`, `cli.py`, `Dockerfile`; reuse `use_cases/export_corpus.py` (`_metadata`, `_file_entry`).
- **DSN-MUI:** `dsn_ingest/export_v2.py`, `__main__.py`, `store.py` (relative paths), `Dockerfile`; reuse `Store.snapshot`, `models.FatwaEntry`.
- **BI:** `src/connectors/bi_source.py` (fixes), `src/pipeline/exporter_v2.py`, `src/cli.py`, `Dockerfile`; reuse `exporter.JsonExporter._format_regulation`.

## Verification

- **Unit (no I/O):** domain rules (identity and alias parsing on real citations from all four corpora, merge/overlay, structure grammars on recorded texts, citations, validity); use cases with in-memory fakes for every port.
- **Architecture:** `test_architecture.py` in the platform and in BPK fails on any inward-rule violation.
- **Contract:** each connector's CI exports a bundle from fixtures and runs `metamorph_contract.validate`.
- **Integration:** the Postgres repositories and `load_bundle` against the compose Postgres:
  - Load the same bundle twice → zero changes.
  - Change one text → new `text_version` + `change_log` row.
  - Override, then the source changes → `conflict`.
- **End to end:** `docker compose up`; trigger each `ingest_*` DAG; then check:
  - `SELECT issuer, count(*) FROM published.document GROUP BY 1` shows all four issuers.
  - Spot checks: POJK 10/POJK.05/2019 has provisions, an `adopts_fatwa` link resolves to a `dsnmui:fatwa:*` document, and UU 21/2011 (from BPK) is the `legal_basis` target of OJK documents.
  - The curation scenario in the web app shows up in `published` after `publish`.
