# Plan: the market data layer, starting with OJK's register of licensed fintech lenders

**Status (2026-10-27):** **Phase 1 is closed:** Steps 1–9 are done, and Step 10 (AWS) is deferred until every phase is built.
- **The connector:** `OJK-Register-Connector` 0.2.0's `ojk-register sync` downloads the lists. The backfill holds 70 editions, December 2019 to July 2026: 68 read whole, and two lose a few rows at a page foot (Step 7).
- **The platform:** it loads the export (243 records) and publishes 166 companies, joining each registration to the license that followed. The read contract is [published-market-schema.md](published-market-schema.md).
- **The pipeline:** `ingest_ojk_register` runs weekly on the local stack, and `metamorph health` checks both the load and the register's freshness.
- **Next:** Phase 2, OJK's portal statistics.

Decided on 2026-10-27:
- **A separate repository** for the connector.
- **Collection by hand for now:** a person downloads each month's PDF and runs `ojk-register import`, until automated download is settled with OJK. *Superseded the same day:* the PDF downloads to a client that names itself, so `sync` collects it, and `import` stays for an edition from elsewhere.
- **OCR only through MinerU:** a PDF page that needs OCR is read by the MinerU service, never by another OCR engine. That includes an edition whose text layer gives no usable table.
- **The license kind is recorded:** a license (`KEP-…`, berizin) or a registration (`S-…`, terdaftar).
- **A registration and its license are one company:** records listed under the same legal name join.

Research behind it: *Market Data Layer: Data Needs and Sources* (the team's doc, 23 Oct 2026).

## Context

The platform serves Phase 4 of the customer journey (compliance and market entry) and part of Phase 3 (product). Phases 1 and 2, macro and industry research, need market data the regulation layer doesn't hold:
- **entities:** who is licensed to do what;
- **statistics:** market size, growth, sharia share, inclusion;
- **reports:** OJK's and BI's yearly reviews, roadmaps, masterplans;
- **events:** licenses granted or revoked, new rules, sanctions.

The market data layer adds them beside the regulation layer, on the same platform:
- **Shared:** connectors, bundles, the loader, Airflow, PostgreSQL, the object store, curation and the AWS deployment.
- **Its own:**
  - a contract (`metamorph-market-contract`);
  - schemas (`market` as the system of record, `published_market` as the read contract);
  - domain modules.
- **Linked to the regulation layer:** a license links to the regulation it is granted under.

**Outcome of this plan's first phase:** every fintech lender OJK has licensed since October 2021, with its sharia or conventional flag and its history on OJK's list. They are published in `published_market` and linked to the POJK that governs them. **Out of scope:** statistics, reports and events beyond list changes (later phases), competitor products and prices (a curated shortlist, later), and news (searched at question time, never stored).

## The phases

Each phase adds one source end to end: connector, contract, load, publish. The contract and schemas grow from real data, one record kind at a time.

| Phase | Source | Record kind | Answers |
|---|---|---|---|
| **1 (this plan)** | OJK's monthly LPBBTI directory | `licensed_entity` | Who lends online under an OJK license, which of them are sharia, and who entered or left |
| 2 | OJK data portal: sharia banking and fintech lending series | `series` | How big the market is, and how fast it grows |
| 3 | BI SEKI tables and the BPS WebAPI | `series` | The macro backdrop |
| 4 | LPKSI, KEKSI, the sharia banking roadmap | report (possibly a non-legal document kind in the regulation layer) | What the regulators plan and report |
| 5 | OJK press releases | `event` | What changed, with an official date |

Phase 2 waits on two answers from OJK (layanan.data@ojk.go.id): may the portal's tables be exported automatically, and is there a bulk route? The answers decide whether Phase 2 is a connector or a monthly import.

## Principles

The [engineering principles](engineering-principles.md) hold here as they do for extraction:
- **General rules from layout only.** The table reader finds columns by their header words and rows by their numbers. It never names a company, an edition or a page.
- **Checks warn; they don't drop data.** A row count that differs from the count OJK states is reported, and the edition still loads. An edition is held back only when no table can be read from it.
- **The connector reports what the list says; the platform interprets.** Being on the July list is a fact the connector reports. "Left the list in July" is derived, and the platform derives it, the same way for every register.
- **No document-specific fixes.** A quirk of one edition is recorded, not patched.
- **Never work around a refusal.** If OJK's site refuses or challenges the connector, the run stops with a critical alert. No headers are faked and no challenge is solved.
- **OCR only through MinerU.** The lists have a text layer, which PyMuPDF reads as tables. A page without one, such as a scanned edition, is read by the MinerU service with OCR (`metamorph-pdf-text`'s `MinerUReader`). Its tables come back as rows of cells and pass through the same table rules. Without a MinerU service configured, such an edition fails with a clear message, and no other OCR engine is tried. `tests/test_architecture.py` guards this.

## Phase 1: the source

**OJK's LPBBTI directory** ([index](https://ojk.go.id/id/kanal/iknb/data-dan-statistik/direktori/fintech/Default.aspx)): one page per edition, roughly monthly, each with one PDF attachment.

| Edition | Page states | Table read with PyMuPDF `find_tables()` (checked 2026-10-27) |
|---|---|---|
| Juli 2026 (31 Jul) | 94 licensed | 94 rows over 6 pages; 7 `Syariah` |
| 31 Desember 2024 | 97 licensed | 97 rows over 6 pages; 7 `Syariah` |
| 5 Januari 2023 | 102 licensed | 102 rows, 7 `Syariah`, but laid out differently: columns in another order, rows numbered `1.`, and a two-line app platform cell (`Android` / `dan iOS`) centred across row borders, so its lines land on the rows above and below |

The July 2026 columns, as headed: `Nomor`, `Nama Perusahaan`, `Nama Sistem Elektronik`, `Surat Tanda Berizin/Terdaftar`, `Tanggal Berizin/Terdaftar`, `Jenis Usaha` (`Konvensional` or `Syariah`), `Alamat Website`, `Sistem Operasi`. The January 2023 header also shows doubled glyphs from overlapping text (`NNamama aS iSsitsetmem`), so header matching must tolerate them.

**Where the editions are:**
- **Since 2024:** `…/direktori/fintech/Pages/…`, titled `Direktori Layanan Pendanaan Bersama Berbasis Teknologi Informasi <date>` or `Penyelenggara Fintech Lending Berizin di OJK per <date>`.
- **From October 2021:** `…/kanal/iknb/financial-technology/Pages/…`. Some of these lists are "Terdaftar dan Berizin", covering both registered and licensed providers.

**Access:**
- The index and edition pages answer a plain HTTP client.
- A direct request for the July 2026 PDF answered with a 245-byte HTML page instead of the file. That request had a generic browser User-Agent (`Mozilla/5.0`).
- **Settled (2026-10-27):** with a User-Agent naming the connector (`ojk-register/0.2.0`), the same PDF downloads, byte for byte what a person downloaded. The site has no `robots.txt`. `sync` makes one request every two seconds, follows the directory's own pager as a browser does, and stops at a refusal or any answer that isn't the PDF asked for. It never imitates a browser or gets past a check.
- The directory lists 79 entries, back to June 2018: 70 lists as PDFs (December 2019 to July 2026), 4 lists as spreadsheets only (not read), and 5 checklists, statistics and an FAQ.

## Phase 1: the connector

A new repository, **`OJK-Register-Connector`** (package `ojk_register`, command `ojk-register`). It is separate from `OJK-Source-Connector`, which owns OJK's legal documents under contract v2. This one collects OJK's registers of licensed entities under the market contract. The LPBBTI directory is its first register. A second register, such as the data portal's company list or FIND, would join it as another adapter once it is checked.

### Layout

It follows BPK-Source-Connector's layers, with `tests/test_architecture.py` enforcing the dependency rule.

```
src/ojk_register/
  domain/                      pure, standard library only
    listing.py      ListedEntity: license number, legal name, platform name, licensed_on, business type
                    (sharia | conventional | unknown), website, app platforms, the row as listed
    licenses.py     license number → entity ID ("KEP-49/D.05/2017" → "ojk:lpbbti:kep-49-d.05-2017");
                    Indonesian dates ("06 Juli 2017", "13 Desember 2019")
    table.py        raw table rows → listed rows: columns found by header words (a last unmatched
                    column takes the last unmatched role), a row opened by a number ("1" or "1."),
                    a row without a number continuing the one above
    checks.py       warnings: row numbers not 1..N, N ≠ the count the page states, a license number
                    missing, a sharia flag missing, a license listed twice
    history.py      one license's listings across editions → the entity as last listed, its other names
  application/
    ports.py        TableReader (PDF → each page's raw rows, and whether it has a text layer), Store
    use_cases/
      import_edition.py      a PDF a person downloaded → kept by sha256 → read
      read_edition.py        PDF → listed rows → stored listings, with the checks' warnings. Pages
                             without a text layer go to the OCR reader, which only MinerU implements
      reread.py              every stored edition read again, with no network
      export_bundle.py       everything held → one market bundle
      check_health.py        the newest edition's age, and whether it was read
  adapters/
    pdf/text_layer.py         PyMuPDF find_tables(): every table on every page, cells as text
    pdf/mineru.py             metamorph-pdf-text's MinerUReader with OCR: its table blocks as rows of cells
    storage/sqlite.py         editions, listings, warnings; the PDFs in data/files/
    storage/market_bundle.py  records → the market contract's BundleWriter
  cli.py, wiring.py, config.py
```

Automated download, `ojk-register sync`: `adapters/web/ojk_directory.py` walks the directory's pager, opens each list's page not kept yet, and downloads its PDF. `application/use_cases/sync.py` imports them oldest first. `domain/directory.py` holds the directory's wording: which entries are lists, an edition's date from its title, and the count its page states.

**State in `data/`,** as in the other connectors, which Airflow bind-mounts:
- `ojk_register.sqlite`;
- `files/<sha256>.pdf`, the editions exactly as downloaded;
- `alerts.jsonl` and `reports/latest.md`.

### Commands

| Command | Does |
|---|---|
| `ojk-register import FILE --edition YYYY-MM-DD [--stated N] [--url URL]` | Keep and read a PDF a person downloaded. `--stated` is the count the edition's page gives, checked against the rows read; `--url` is where it came from |
| `ojk-register reread` | Read every stored edition again, with no network: after the table reader changes |
| `ojk-register export --out DIR --run-id ID` | Everything held → one market bundle |
| `ojk-register status` | Editions held, and licenses per edition, sharia and conventional |
| `ojk-register health` | Exit `0` ok, `1` warning, `2` critical, for a scheduler |

### What it exports

One bundle per run: a full snapshot of every license ever seen, plus every edition's PDF as a blob. That is about 60 editions of 300 KB, around 18 MB. One record per license:

```text
MarketRecord (market contract 1.0, kind licensed_entity)
  source        connector "ojk-register", connector_version, source_id (the license number as printed),
                url (the newest edition's page), fetched_at
  entity        id "ojk:lpbbti:kep-49-d.05-2017"
                register "ojk:lpbbti"
                legal_name, names[] (platform names, earlier legal names)
                business_type sharia | conventional | unknown
                license: number, date, kind (license | registration | unknown)
                website, channels (android, ios)
  listings[]    one per edition the license appears in: edition date, file sha256, page, row number,
                the row as listed
  files[]       the editions' PDFs: sha256, role "register_edition", source_url, edition date
  source_fields the newest listing's cells, unchanged
```

**Identity.** A license number is the stable key across editions. A company and its platform get renamed, but their license keeps its number. A company that is re-licensed under a new number appears as a new entity. Joining such entities, and joining one company across registers, is the platform's entity resolution, built when a second register arrives.

## Phase 1: the market contract

A new package, `packages/metamorph-market-contract`, beside `metamorph-contract`. It is separate because contract v2's bundle is built around `NormalizedDocument` (`bundle.py`). It mirrors that package:
- a JSON Schema per record kind (`urn:metamorph:market:1.0:licensed-entity`) and one for the manifest;
- Python types that mirror the schemas, with a test that fails on drift;
- `problems(record)`;
- a `BundleWriter` and `Bundle` with the same guarantees as contract v2: written to `records.jsonl` plus `blobs/`, and a manifest written last, only on a clean exit.

Only `licensed_entity` is defined now. Phase 2 adds `series` when its first source is in hand.

## Phase 1: the platform

| Piece | What |
|---|---|
| Migration `0016_market` ✓ | `market.register` (ID, issuer, name, governing regulations, `fresh_days`), `market.entity` (each record whole, with its package hash), `market.file`. `published_market.register`, `edition`, `company`, `entity`, `listing`. No `change_log`: each publish rebuilds the schema in one transaction. Loads are recorded in `ingest.bundle` and `ingest.quarantine`, as contract v2 loads are |
| `domain/market/` ✓ | Standing: first and last edition per license, and "left the list after edition X". Companies: records listed under the same legal name join. Edition changes: listed, joined, left. Review notes in place of a gate: an unknown business type or kind is noted, never held back. The publication: records → published rows |
| `application/load_market_bundle.py`, `publish_market.py` | The loader's guarantees as today: quarantine invalid records, idempotent by package hash, one transaction per record |
| CLI | `metamorph market load BUNDLE`, `metamorph market publish` |
| The link to the regulation layer | `market.register` names the regulations that govern each register. For `ojk:lpbbti`: `ojk:pojk:2024:40`, which replaced POJK 10/2022, and `ojk:seojk:2025:19`, which replaced SEOJK 19/2023. Both confirmed in the registry on 2026-10-27. Kept as data, curated, never inferred per entity |
| Health ✓ | Register freshness: a warning when the newest published edition is older than `market.register.fresh_days` (90 for `ojk:lpbbti`: OJK publishes each list one to three months after its date). The connector's load cadence joins `CADENCE` with the Airflow job (Step 9) |
| `docs/published-market-schema.md` | The read contract for the Knowledge and Retrieval layer |
| Airflow | `ingest_ojk_register`, Mondays: export what is held, then `metamorph market load`, then publish. Weekly, because OJK publishes each edition on no fixed day. While collection is by hand, imports land in the connector's `data/`, and the job picks them up at its next run |

Curation of market records (overrides, suppressions) waits for a real need. Quarantined records already reach the review queue through `ingest.quarantine`.

## Steps

Each step is small, test first, and leaves everything green.

| # | Step | Done when |
|---|---|---|
| 0 | **Check before building.** (a) Access: decided, collection by hand for now. (b) Survey every edition since October 2021: title, date, count stated, columns, layout. (c) The governing regulations: done, `ojk:pojk:2024:40` and `ojk:seojk:2025:19` | A table of editions with their layouts |
| 1 ✓ | The market contract package: schema, types, validator, bundle writer and reader | Its tests pass, including the schema-drift test |
| 2 ✓ | The connector's skeleton: `pyproject.toml`, the CLI, config, the Dockerfile, the architecture test | `uv run pytest` and `ojk-register --help` work |
| 3 ✓ | The table reader, on three fixture editions (January 2023, December 2024, July 2026) | It reads each edition's stated count: 102, 97 and 94; 7 sharia in each; continuation rows merged; doubled-glyph headers matched |
| 4 ✓ | Domain: license IDs, Indonesian dates, checks, history. The edition's date is given at import, so no title parsing yet | Unit tests |
| 5 ✓ | OCR through MinerU: pages without a text layer go to `MinerUReader`; without a MinerU service the edition fails clearly | A fake reader in tests; a guard against any other OCR engine |
| 6 ✓ | Store, `import`, `reread`, `export`, `health`, `status` | A fixture import exports a bundle whose every record `is_valid` |
| – ✓ | Automated download, `sync`: the directory's real pages replayed in tests | Every list in the directory downloaded and imported, with a User-Agent naming the connector |
| 7 ✓ | Backfill every edition: `ojk-register sync`, 70 editions. The general rules it needed:<br>• rows joined by vertical position, so a centred cell no longer merges rows;<br>• the May 2026 header (a blank number header, two `Jenis Usaha` columns);<br>• `147..` as a row number;<br>• any dash in a license number;<br>• OCR by MinerU when at most half the rows carry a license number.<br>68 editions read whole (March 2023 through MinerU). December 2019 and February 2020, also through MinerU, lose 3 and 2 rows at page 2's foot, which warns | Every edition read; each mismatch triaged |
| 8 ✓ | Platform: migration `0016_market`, `domain/market/` (standing, companies, edition changes, review notes, the publication), `load_market_bundle`, `publish_market`, `metamorph market load` and `publish`, register freshness in `metamorph health`, [published-market-schema.md](published-market-schema.md). An unknown business type or kind is a review note, not a hold (engineering principles, 2026-10-22). **Run 2026-10-27** on the backfill export, in a throwaway database: 243 records loaded, then 243 unchanged on a second load; 166 companies (94 licensed, 72 left); every gate below holds | `metamorph market load` and `publish` over the backfill bundle; database tests pass |
| 9 ✓ | Airflow job `ingest_ojk_register` (Mondays 02:45 UTC): `ojk-register sync` and export → `metamorph market load --publish` → discard. Jobs carry their layer (`Layer.MARKET`), so a market bundle never triggers the registry build. Compose service `ojk-register` builds `metamorph/ojk-register:dev`. `ojk-register` joins health's load cadence (weekly). **Run 2026-10-27** on the local stack, after a backup (`backups/2026-10-27-before-market-layer/`) and migration 0016 on the live database: collect, load and discard all succeeded; 243 records loaded; 166 companies published; no new edition at OJK yet | A `dags test ingest_ojk_register` run loads and publishes locally |
| 10 | AWS: the job joins the ingestion layer's `jobs.yaml` once that layer is deployed. **Deferred by the project owner (2026-10-27)** until every phase is built; `tests/test_dag_jobs.py` names the image in `ECS_DEFERRED` until then | Waits on the ingestion layer's access |

## Validation

**Gates: Phase 1 is done when these hold.**
- Every edition held is read, and each edition's row count equals the count its page states. A mismatch is triaged by hand and recorded.
- Every license in the newest edition has a business type, sharia or conventional.
- Month-to-month changes add up: last month's count, plus licenses joining, minus licenses leaving, equals this month's count, for every pair of editions.
- Ten licenses checked by hand against their PDFs: name, license number, date and business type.

**Monitored, never blocking on its own:** an unknown column, a website that changed, a platform name that changed.

## Risks and open questions

| Risk | What happens | What to do |
|---|---|---|
| OJK challenges automated downloads | The connector can't collect | Ask OJK; meanwhile a monthly `import` by a person, about 5 minutes a month |
| The layout changes again | Rows are misread | Columns are found by header words and checked against the stated count; a mismatch warns at once |
| OJK moves the list to its data portal or FIND | The PDF stops | The contract and platform stay the same; a new adapter reads the new source |
| A license number is printed differently in two editions | One license looks like two | Case, spaces and every dash shape are normalised: four 2020 licenses printed `KEP – 16/…` with an en dash merged with their `KEP-16/…` selves |
| Early lists mix registered and licensed providers | Registered ones look licensed | **Done:** `license.kind` in the contract, from the number's form: 140 registrations, 103 licenses, none unknown. A company registered then licensed has two records (70 do). Joining them by company is the platform's to decide in Step 8 |
| A cell centred across row borders | PyMuPDF's `find_tables()` splits a printed row into sub-rows | **Fixed:** a row without a number joins the numbered row nearest it on its page. 30 editions from 2020–2022 and September 2024 now read whole, and January 2023's Android/iOS limit is gone. Merged licenses: 189 of 403 records before, 0 of 243 after |
| MinerU cuts the foot of a long page | A few rows lost | December 2019 and February 2020, 5 rows in all; the numbering gap warns. Recorded, not fixed: two of the oldest editions |

**Open questions:**
- Does OJK's [FIND](https://find.ojk.go.id/) cover every sector with export? If so, it may become the register for every other sector, as one more adapter.
- Should a license's sharia unit (UUS) be modelled? OJK allows fintech lenders to open one. The directory doesn't show it today.

## Critical files

| File | Role |
|---|---|
| `packages/metamorph-market-contract/` | The market contract: schemas, types, bundle |
| `OJK-Register-Connector/src/ojk_register/domain/table.py` | The general table rules |
| `OJK-Register-Connector/src/ojk_register/adapters/ojk/directory.py` | Access to OJK, and where a refusal stops the run |
| `src/metamorph_platform/adapters/postgres/migrations/0016_market.sql` | The `market` and `published_market` schemas |
| `src/metamorph_platform/domain/market/` | Listing history and the gate |
| `docs/published-market-schema.md` | The read contract for the Knowledge and Retrieval layer |
