# Plan: the market data layer, starting with OJK's register of licensed fintech lenders

**Status (2026-10-28):** **Phase 1 is closed:** Steps 1–9 are done, and Step 10 (AWS) is deferred until every phase is built.
- **The connector:** `OJK-Register-Connector` 0.2.0's `ojk-register sync` downloads the lists. The backfill holds 70 editions, December 2019 to July 2026: 68 read whole, and two lose a few rows at a page foot (Step 7).
- **The platform:** it loads the export (243 records) and publishes 166 companies, joining each registration to the license that followed. The read contract is [published-market-schema.md](published-market-schema.md).
- **The pipeline:** `ingest_ojk_register` runs weekly on the local stack, and `metamorph health` checks both the load and the register's freshness.
- **Phase 2, OJK's portal statistics, is built (2026-10-27):** Steps 0–8 are done, and AWS (Step 9) is deferred with Phase 1's. The workbooks' older history (Step 10) waits for a need.
  - **The connector:** `OJK-Stats-Connector` 0.1.0 collects 78 of the portal's 86 tables, using the requests its own page makes (decision B).
  - **The platform:** it publishes 2,182 series and 90,677 observations, with each industry linked to its regulations.
  - **The pipeline:** `ingest_ojk_stats` runs weekly on the local stack (paused, like the others), and `metamorph health` checks both the load and the newest month.
- **Phase 3, the macro backdrop, is live but for BPS's backfill (2026-10-28):** BI's SEKI tables (3a) and BPS's dynamic tables from its website (3b), both decided by the project owner. AWS (Step 9) is deferred with the others.
  - **Built:** the contract's frequencies, units and marks; `BI-Stats-Connector`; `BPS-Stats-Connector`; migration 0018, partial bundles and the two DAGs.
  - **SEKI is live:** bi.go.id refuses the connector, so a curator downloads each month's edition and `bi-stats import` reads it (option A). September 2026's edition is published: 107 tables, 6,919 series.
  - **BPS is partly live:** 116 tables are published. Its first collection runs on (Step 12): BPS's server answers slowly and often fails, so it takes days.
  - **Cross-checked:** BPS's inflation and GDP equal SEKI's to the digit.

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
| 2 | OJK's statistics: fintech lending (Statistik LPBBTI) and sharia banking (SPS), from OJK's monthly workbooks and then its data portal | `series` | How big the market is, how fast it grows, and the sharia share |
| 3 | BI's SEKI tables (3a), then BPS's dynamic tables (3b) | `series`, with quarters, years and units | The macro backdrop |
| 4 | LPKSI, KEKSI, the sharia banking roadmap | report (possibly a non-legal document kind in the regulation layer) | What the regulators plan and report |
| 5 | OJK press releases | `event` | What changed, with an official date |

Phase 2 was to wait on two answers from OJK (layanan.data@ojk.go.id): may the portal's tables be exported automatically, and is there a bulk route? The portal's FAQ answers the second: there is no API yet. The first is still open, and it now decides only how the months after OJK's cutover are collected. The history before it comes from workbooks the connector can download (Phase 2: the sources).

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

## Phase 1: steps

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

## Phase 1: validation

**Gates: Phase 1 is done when these hold.**
- Every edition held is read, and each edition's row count equals the count its page states. A mismatch is triaged by hand and recorded.
- Every license in the newest edition has a business type, sharia or conventional.
- Month-to-month changes add up: last month's count, plus licenses joining, minus licenses leaving, equals this month's count, for every pair of editions.
- Ten licenses checked by hand against their PDFs: name, license number, date and business type.

**Monitored, never blocking on its own:** an unknown column, a website that changed, a platform name that changed.

## Phase 1: risks and open questions

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

## Phase 1: critical files

| File | Role |
|---|---|
| `packages/metamorph-market-contract/` | The market contract: schemas, types, bundle |
| `OJK-Register-Connector/src/ojk_register/domain/table.py` | The general table rules |
| `OJK-Register-Connector/src/ojk_register/adapters/web/ojk_directory.py` | Access to OJK, and where a refusal stops the run |
| `src/metamorph_platform/adapters/postgres/migrations/0016_market.sql` | The `market` and `published_market` schemas |
| `src/metamorph_platform/domain/market/` | Standing, companies, edition changes, the publication |
| `docs/published-market-schema.md` | The read contract for the Knowledge and Retrieval layer |

## Phase 2: the sources

Checked on 2026-10-27 with a client naming itself (`ojk-register/0.2.0`), as in Phase 1.

**OJK moved both statistics to its data portal,** [data.ojk.go.id](https://data.ojk.go.id/SJKPublic), launched on 17 March 2025:
- **Sharia banking (SPS):** from July 2025's data on;
- **Fintech lending (Statistik LPBBTI):** from January 2026's data on.

The months before stay on ojk.go.id as monthly workbooks.

| | Workbooks on ojk.go.id | The data portal |
|---|---|---|
| **Periods** | SPS to June 2025; LPBBTI to December 2025. Nothing new will be added | SPS from July 2025; LPBBTI from January 2026 |
| **Where** | One page per month, with an `.xlsx` (and for SPS a PDF), under a paged index like Phase 1's directory: [SPS](https://ojk.go.id/id/kanal/syariah/data-dan-statistik/statistik-perbankan-syariah/Default.aspx), [LPBBTI](https://ojk.go.id/id/kanal/iknb/data-dan-statistik/fintech/Default.aspx) | A JavaScript application. A dataset is chosen in steps (industry → information group → metric → measures), posted with the page's anti-forgery token, then shown as a pivot grid |
| **Access** | Downloads with the connector's own User-Agent, as Phase 1's PDFs do | No account. Excel and CSV download offered for every table (FAQ). **No API:** "belum tersedia", promised later (FAQ). No `robots.txt` |
| **Reuse** | OJK's terms: quoting is allowed with the source named in full ([syarat dan kondisi](https://ojk.go.id/id/Pages/syarat-dan-kondisi.aspx)) | The same, "secara bertanggung jawab" (FAQ) |

**OJK's mapping files** map each old table to its place on the portal, and say how to pivot it there:
- [LPBBTI](https://ojk.go.id/id/kanal/iknb/data-dan-statistik/fintech/Documents/Mapping%20Statistik%20LPBBTI.xlsx): 55 rows, covering tables 1–18, conventional and sharia, plus the sharia overview. 10 rows are "Belum tersedia" (tables 10 and 13–16).
- [SPS](https://ojk.go.id/id/kanal/syariah/data-dan-statistik/statistik-perbankan-syariah/Documents/Default/Mapping%20Statistik%20Perbankan%20Syariah%20SPS.xlsx): tables 1–25 (sharia commercial banks and units). Tables 4 and 5 have no portal counterpart. The BPRS tables (26–47) aren't mapped.

**What the workbooks hold:**

| | Statistik LPBBTI, December 2025 | SPS, June 2025 |
|---|---|---|
| **Size** | 393 KB, 24 sheets: 18 tables, `Overview LPBBTI Syariah`, cover, glossary | 4.6 MB, 61 sheets: 47 tables, BUS and UUS (1–25) and BPRS (26–47) |
| **Periods** | The latest 13 months, as real dates in the header row (`2024-12-01` … `2025-12-01`). Table 1 is one month (`Periode : Desember 2025`) | A long history in each table, from 2014: years, then months, as a year row over a month row (`2014` / `Jun`) |
| **Rows** | Bilingual labels (Indonesian, then English in the last column), nested by section rows (`Aset` › `Aset Lancar` › `Kas dan Setara Kas`) | Bilingual labels, nested by prefixes (`-`, `a.`, `1.`) and section rows |
| **Values** | Numbers. Units in the labels: `miliar Rp`, `Akun`, `%`; TWP90 as a fraction (`0.029`) | Mostly numbers. Revised values are text marked `r)`, in either locale: `14,60 r)` (a CAR of 14.60%), `17,904 r)` (capital of 17,904 billion), `18.229 r)` |
| **Measures per period** | One, or several (table 9: borrower accounts, outstanding loans, TWP90 for each month) | One, or several (the Dati I and II tables) |

**What the portal holds (Step 0, 2026-10-27).** It holds far more than OJK's notices say:
- **Its own history:** BPR Syariah from December 2019, Bank Umum Syariah (with its sharia units) from January 2023, LPBBTI from January or July 2024.
- **86 tables (cubes) with 108 measures** across the four industries in scope.
- **One OLAP cube per table, queried over XMLA.** The dataset page's pivot table (DevExtreme's `XmlaStore`) posts MDX to `/SJKPublic/datasource/`. The answer gives each member's key (e.g. the account `110001010100`), its label (`003. 1. Kas dan Setara Kas`) and the value, in whole rupiah or as a count.
- **One year of months per request.** The page's default filter is one year. A request for twelve years of months was answered with the firewall's "Request Rejected" page, so the connector keeps to the page's shape.

So the portal alone gives the series from those months on. The workbooks are needed only for the months before them, and the order of work changed: the portal first, the workbooks' older history later (Step 10).

**Cross-checked against the workbooks,** OJK's separate publication, for months both cover:
- **Equal:**
  - Bank Umum Syariah in June 2025: 14 banks, assets of Rp 653,889,592,228,737, i.e. the workbook's 653,889.59 billion;
  - its sharia units: 19, Rp 288,652.84 billion;
  - BPR Syariah: 173 banks, the same count in every province;
  - LPBBTI lenders in December 2025: 88 conventional and 7 sharia.
- **Different:** LPBBTI's balance sheet for December 2025. The portal gives assets of 10,823.72 billion (conventional) and 122.54 billion (sharia); the workbook gives 11,147.3 and 121.31. The portal's two cubes agree with each other, and liabilities and equity differ too, so this looks like a restatement after the workbook was published. It is recorded and monitored, not fixed: the portal is OJK's newer publication.

## Phase 2: the design

**One record kind, `series`,** added to market contract 1.0 in place. 1.0 is not published yet, as when `License.kind` was added; `licensed_entity` is unchanged.

```text
SeriesRecord (market contract 1.0, kind series)
  source         connector "ojk-stats", connector_version,
                 source_id (cube/measure/member unique names, e.g. BU_Syariah_PosisiKeuangan/[Measures].[Posisi Keuangan]/
                 [Akun].[Akun].&[110001010100]), url (the dataset page), fetched_at
  series         id "ojk:portal:bu_syariah_posisikeuangan:posisi-keuangan:akun=110001010100"
                 dataset "ojk:portal:bu_syariah_posisikeuangan" (the cube), industry, group, metric, measure
                 (as the portal names them), dimensions[] (name, key, label)
  observations[] period (YYYY-MM), value (as given, never rescaled), file (the answer it came from)
  files[]        the XMLA answers: sha256, role source_answer, text/xml, source_url, edition (the cube's last update)
  source_fields  catalog, cube, metric_id, measure, members as the portal gives them
```

**Identity:** a series is one measure of one cube, for one member of each dimension in the page's default layout. It is keyed by the members' keys, never their labels, so a renamed account keeps its series. A dimension the default layout leaves out is summed over, as the page shows it.

**Revisions:** the connector keeps the newest answer per cube, measure and year. A value a later answer changes is counted and reported, and never held back.

### The connector

A new repository, **`OJK-Stats-Connector`** 0.1.0 (package `ojk_stats`, command `ojk-stats`), with OJK-Register-Connector's layers and architecture test. Its tests replay real pages and answers saved on 2026-10-27.

```
src/ojk_stats/
  domain/
    portal.py      the page's layout → measures and dimensions (the calendar left out); months one year
                   per request; Industry, Table
    series.py      Member, Cell; series and dataset IDs from keys; answers → series, newest label;
                   values a later answer changed
  application/
    ports.py       Portal, Store, BundleExporter; SourceRefused, TableUnreadable
    use_cases/     collect.py, export_bundle.py, check_health.py, status.py
  adapters/
    web/ojk_portal.py   the page's own requests: lists, SaveMeasures with its token, the dataset page, XMLA
    web/xmla.py         the pivot's MDX statements; answers → cells; faults
    storage/sqlite.py, storage/market_bundle.py
```

**Access rules,** the project owner's decision B below:
- one request every two seconds, with a User-Agent naming the connector;
- only the requests the page makes;
- **a refusal stops the run:** an HTTP error, the firewall's page, the wrong content type, or an answer to a different question;
- **a cube OJK hasn't updated since it was last collected whole is skipped:** its months are asked, nothing else.

**A table the portal itself can't show is noted and skipped.** Its page's layout names a dimension its cube lacks, so the cube answers with a fault, and the page's own pivot shows nothing either. 8 of 86 tables do this today:
- seven LPBBTI tables by lender or borrower category, conventional and sharia, whose layout names `[Kateri Pemberi]` or `[Kateri Penerima]` (sic);
- `LPBBTI_TotalLiabilitas`, whose layout names `[DATI1]`.

They are asked again each run. No other query is guessed: guessing would be a fix for one document.

### The platform

| Piece | What |
|---|---|
| Migration `0017_market_series` ✓ | `market.statistics_source` (`ojk:portal`, `fresh_days` 120), `market.industry` (curated links), `market.series` (each record whole, with its package hash). `published_market.dataset`, `series`, `observation` |
| `domain/market/statistics.py` ✓ | The published rows from the series records. A dataset takes its industry's links |
| Load and publish ✓ | `metamorph market load` takes both kinds. A series from an unknown source waits in quarantine, as a record from an unknown register does. Publish rebuilds registers and statistics in one transaction; observations go in by `COPY` |
| The links ✓ | Curated in `market.industry`, all in the registry: LPBBTI (conventional and sharia) → the register `ojk:lpbbti` and its regulations; Bank Umum Syariah → `id:uu:2008:21`, `ojk:pojk:2022:16`, `ojk:pojk:2023:12`; BPR Syariah → `id:uu:2008:21`, `ojk:pojk:2024:7` |
| Health ✓ | `statistics ojk:portal`: a warning when the newest published month ended more than 120 days ago. `ojk-stats` joins the load cadence (weekly) |
| `docs/published-market-schema.md` ✓ | The dataset, series and observation tables, with example queries |
| Airflow ✓ | `ingest_ojk_stats`, Mondays 03:15 UTC, `Layer.MARKET`: `ojk-stats collect` and export → `metamorph market load --publish` → discard. Compose service `ojk-stats` builds `metamorph/ojk-stats:dev` |

## Phase 2: decisions

**How the portal's months are collected.** No new month will appear in the workbooks: from July 2025 (SPS) and January 2026 (LPBBTI), the portal is the only source.

| Option | What | Cost |
|---|---|---|
| **A. A person exports** | Each month, a person downloads the portal's Excel export for each metric, and the connector reads it | About 40 metrics, each month |
| **B. The connector runs the portal's own page requests** | The same requests the page makes, by Phase 1's rules: a User-Agent naming the connector and a contact, one request every two seconds, stop at any refusal | The portal offers no API, so this drives an interface OJK hasn't published, and it could change without notice |
| **C. Wait for OJK** | Ask layanan.data@ojk.go.id whether B is acceptable, and when the API comes | Unknown |

**Decided by the project owner (2026-10-27): B.** The connector makes the portal page's own requests, with Phase 1's rules:
- a User-Agent naming the connector and, when configured, a contact;
- one request every two seconds;
- a stop with a critical alert at any refusal or unexpected answer.

It calls only what the page itself calls. It never probes for other endpoints, and it never gets past a check. An email to OJK (layanan.data@ojk.go.id) naming the connector is still advised. If OJK objects, collection falls back to A. When the API ships, it replaces B.

**Order, changed by Step 0:** first the portal, which holds every industry from 2019, 2023 or 2024; then the workbooks' older history (Step 10).

## Phase 2: steps

| # | Step | Done when |
|---|---|---|
| 0 ✓ | **Check before building.** The portal's industries, groups, metrics and cubes surveyed; its history found; the one-year request shape found; the SPS regulations confirmed in the registry; the portal cross-checked against the workbooks (above) | A table of the 86 tables and their months |
| 1 ✓ | Market contract 1.0 grows the `series` kind: schema, types, `problems()`, codec, bundles of either kind | 41 contract tests pass, including drift |
| 2 ✓ | The connector's skeleton, the architecture test | `uv run pytest` and `ojk-stats --help` work |
| 3 ✓ | The portal's wording (layout, months) and series (keys, IDs, gathering, revisions) | Unit tests |
| 4 ✓ | The XMLA reader and the portal adapter, replayed from real answers: one and two dimensions, none, a fault, a firewall rejection | Adapter tests |
| 5 ✓ | `collect`, the store, `export`, `status`, `health`, the CLI | A collected store exports a bundle whose every record `is_valid` |
| 6 ✓ | **The first collection, 2026-10-27:**<br>• 78 tables read, about 90,000 values, in about 35 minutes;<br>• 8 noted as unreadable (above);<br>• stopped once, rightly: the first run met a fault it didn't recognise yet, and stopped. Faults are now read as unreadable tables | Every table read or noted |
| 7 ✓ | Platform: migration 0017, statistics, load and publish by kind, statistics freshness, the read contract. **Run 2026-10-27** in a throwaway database:<br>• the register's bundle (243) and the statistics bundle loaded: 2,182 series, 34 MB with 18 MB of answers;<br>• a second statistics load all unchanged;<br>• published: 78 datasets, 2,182 series, 90,677 observations, beside 166 companies;<br>• health `statistics ojk:portal` ok, newest month 2026-08 | Database tests pass; the gates below hold |
| 8 ✓ | Airflow `ingest_ojk_stats` on the local stack. **Run 2026-10-27**, after a backup (`backups/2026-10-27-before-market-series/`, 98 MB) and migration 0017 on the live database:<br>• collect, load and discard all succeeded;<br>• collect asked only each cube's months, every cube being unchanged since its first collection, and noted the same 8 unreadable;<br>• 2,182 series loaded and published with the register's 166 companies;<br>• `metamorph health`: `ojk-stats` and `statistics ojk:portal` ok | A `dags test` run loads and publishes locally |
| 9 | AWS | Deferred with Phase 1's Step 10 |
| 10 | The workbooks' history before the portal's months: LPBBTI before 2024, Bank Umum Syariah before 2023. Their layout rules (years over months, `r)` marks, text numbers) are planned in Phase 2: the sources | Waits on a need for the older years |

## Phase 2: validation

**Gates, tied to how answers use the figures:**
- **Every table read or noted:** 78 read, and 8 noted as unreadable, each for the same reason, its page's own layout fault.
- **Values match OJK's other publication:** the workbook cross-check above. Counts and the sharia banks' assets are equal. LPBBTI's December 2025 balance sheet differs, recorded as a restatement.
- **Every industry linked to its regulations,** all present in the registry.
- **Operations:**
  - a second load is all unchanged;
  - the publish is one transaction;
  - a refusal stops the run;
  - a cube unchanged since its last collection is skipped.

**Monitored, never blocking on its own:**
- revisions;
- unreadable tables;
- a cube whose newest month lags the others (several LPBBTI cubes end in April 2026 while most reach August).

## Phase 2: risks

| Risk | What happens | What to do |
|---|---|---|
| OJK objects to B, or the firewall starts refusing | Collection stops with exit 2 and a failed task | Email OJK first. If OJK objects, fall back to A |
| The portal changes its page or cube names | Series start anew or the run stops | It stops at the first unexpected answer. Series are keyed by member keys, so relabels don't split them |
| OJK fixes a broken layout | 8 more tables read | Nothing to do: they are asked each run |
| A restatement changes past months | Values change | The connector counts revisions, and the platform publishes the newest |
| The bundle grows: 34 MB a week, 18 MB of it answers | Disk and object store use | Answers are stored by sha256, so unchanged ones are stored once. The bundle is discarded after loading |

## Phase 3: the sources

Checked on 2026-10-27 with clients naming themselves, as in Phases 1 and 2. The macro backdrop has two sources, and they differ most in access.

| | BI's SEKI | BPS's WebAPI |
|---|---|---|
| **What** | *Statistik Ekonomi dan Keuangan Indonesia*, monthly: money and banking, non-bank finance, money and capital markets, government finance, balance of payments, external debt, GDP, prices, international indicators. 108 tables. BPS's GDP and CPI are among them, as secondary data | BPS's own statistics, as dynamic tables: variables by region, derived variable and period, with units and notes. 549 domains (national, 34 provinces, 514 regencies) |
| **Where** | The [SEKI page](https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Default.aspx) links each table as `.xls` and `.pdf` (`/SEKI/tabel/TABEL1_1.xls`). Each month's edition is also one zip (8.5 MB, September 2026's) | A JSON API, `webapi.bps.go.id/v1/api/…`, documented by an [OpenAPI spec](https://webapi.bps.go.id/documentation/) |
| **Access** | No account. `robots.txt` allows `/SEKI/`. The tables answer a conditional request (`If-Modified-Since`) with `304`, so an unchanged table costs nothing. **But on 2026-10-27 bi.go.id reset the connector's connections** (Step 6), so a curator downloads each edition (option A) | **A registered application and a key.** BPS may verify, refuse or limit a registration; requests are rate-limited (limits unpublished) |
| **Reuse** | The SEKI pages link no terms. BI names its data sources; we cite "Bank Indonesia, SEKI" and the table | [Terms](https://webapi.bps.go.id/developer/): **commercial use needs BPS's approval or an agreement** (§6). The key is secret and never in a repository (§3). Every app showing the data must say *"Layanan ini menggunakan API Badan Pusat Statistik (BPS)."* (§5) |

**What SEKI holds (surveyed 2026-10-27, September 2026's edition):**
- **One layout in 105 of 108 tables,** read from the current (last) sheet:
  - a title row and a unit row (`(Miliar Rp)`), in Indonesian, with English at the far right;
  - a year row over a period row: months (66 tables) or quarters (39). A blank period after December or Q4 is the year's own figure;
  - numbered rows (`1`, `2`, … in the first column, repeated at the far right), the Indonesian label, then the values;
  - **nesting by Excel's cell indent,** levels 0 to 8: `Simpanan Berjangka (Rupiah dan Valas)` › `Rupiah`;
  - provisional periods marked `*` (*angka sementara*) or `**` (*sangat sementara*): `Aug*`, `Q2**`.
- **Three tables have years only:** government revenue, spending and financing (IV.1–IV.3). Their headers repeat two years in hidden, empty columns.
- **About 3,400 series and 310,000 values,** from 2010 for most tables.
- **Older history in earlier sheets** (`Th 1985-1992`, …). The banking tables I.4–I.24 hold only 20 months in their current sheet: BI revised their concepts from June 2025's edition (giro, KBLI 2015 sectors, bank groups after POJK 12/2021, credit approvals, UMKM; [BI's notice](https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Documents/Informasi-Publikasi-SEKI-2025.pdf)). An earlier sheet is a different concept, not a continuation.
- **Tables are updated one by one** during the month (1–13 October for September), before the edition's zip (15 October). One table has stopped: IX.9, world commodity prices, ends in June 2017.
- **Sharia figures are few:** the rates table I.25 includes sharia instruments (PUAS, SBSN repo). Sharia banking itself is OJK's (Phase 2).

**What BPS adds beyond SEKI:** population, labour, poverty, consumption and every figure by province. Its *strategic indicators* endpoint lists BPS's own chosen headline indicators with their variable IDs: a scope BPS sets, not us. Nothing beyond the public spec has been called: the data needs a key.

## Phase 3: the design

**3a, SEKI, comes first:** it needs no account. **3b, BPS,** follows from bps.go.id's own pages (below).

### The contract

The `series` kind grows, in place at 1.0, with **optional fields only,** so the 2,182 records Phase 2 loaded stay valid:
- **Periods:** `2026-08` (a month), `2026-Q2` (a quarter), `2026-S1` (a half-year), `2025` (a year). One series keeps to one kind.
- **`series.frequency`:** `monthly`, `quarterly`, `semiannual` or `annual`. Absent means monthly.
- **`series.unit`:** as the source states it (`Miliar Rp`, `Persen`, `Indeks`). Never inferred, never converted.
- **`series.industry`:** may be null. Macro series belong to no industry.
- **`observation.provisional`:** true when the source marks the period provisional.
- **A file role, `source_table`:** a workbook or a page's answer as downloaded.

### Identity

- **Dataset:** one SEKI table, `bi:seki:tabel1_1`.
- **Series:** one numbered row at one frequency: `bi:seki:tabel1_1:monthly:row=5`. The table's year columns give an `annual` series beside the monthly or quarterly one, as BI states them; nothing is summed.
- **The row number is BI's own,** printed on both sides of every row: the nearest thing SEKI has to a key. Every edition re-sends a table's whole history under its current numbering, so a series never mixes two rows of one edition. **A row whose label changes under the same number is reported** (monitored), in case BI renumbers.
- **The label is the path of labels by indent:** `Uang Kuasi › Simpanan Berjangka (Rupiah dan Valas) › Rupiah`. The English label is kept in `source_fields`.
- **Values as given:** a number, or no observation for `-` and blanks.

### The reading rules

General rules from layout, one set for every table:
- **The period row** is the header row of month or quarter names. Without one, the year row is the period row.
- **Years are counted, not read off:** from the first year label, a January (or Q1) after December (or Q4) starts the next year. Each year label must lie within its own year's columns. When one doesn't, the table is noted unreadable.
- **A column without values is skipped,** hidden or not.
- **A period given two different values in one row** notes the table unreadable. Nothing is guessed.
- **A data row** starts with a number in its first column.

### The connector

A new repository, **`BI-Stats-Connector`** 0.1.0 (package `bi_stats`, command `bi-stats`), shaped like OJK-Stats-Connector: domain, application, adapters, and the architecture test. It doesn't join `BI-Source-Connector`, which serves the regulation contract.

```
src/bi_stats/
  domain/
    seki.py        periods (months, quarters, years, provisional marks), rows and their indent paths, units
    series.py      dataset and series IDs from row numbers; tables → series; revisions; relabelled rows
  application/
    ports.py       Seki (the index and its tables), Store, BundleExporter; SourceRefused, TableUnreadable
    use_cases/     collect.py, export_bundle.py, check_health.py, status.py
  adapters/
    web/bi_seki.py       the SEKI page → table links; each table by conditional GET
    workbook/xls.py      .xls → a grid of cells with indents and hidden columns (xlrd)
    storage/sqlite.py, storage/market_bundle.py
```

**Access rules,** as in Phases 1 and 2:
- one request every two seconds, with a User-Agent naming the connector and, when configured, a contact;
- **only the links the SEKI page shows:** the page, then each table's `.xls`;
- **a refusal stops the run:** an HTTP error, a challenge page, or a file that isn't a workbook;
- **an unchanged table costs one `304`.** A weekly run is about 110 requests.

**Commands:** `bi-stats collect | status | export | health`, as `ojk-stats`.

### The platform

| Piece | What |
|---|---|
| Migration `0018_market_frequency` | `market.statistics_source` gains `citation` and the rows `bi:seki` (`fresh_days` 90) and `bps:table` (`fresh_days` 120: freshness is the newest period of any table, and BPS's monthly price tables appear within weeks). `published_market.dataset.industry` becomes nullable and the dataset gains `citation`. The series table gains `frequency` and `unit`, and the observation table gains `provisional`. Observations keep `period` as the period's first day |
| `domain/market/statistics.py` | Periods by frequency. A dataset without an industry is published unlinked |
| Partial bundles | A series is marked missing only when its dataset is in the bundle without it, so a bundle may carry only changed datasets |
| Health | `statistics bi:seki` and `statistics bps:table`: the newest period's **end** (a quarter's, a year's), not its start. Each dataset's own lag is shown by `status`, monitored |
| `docs/published-market-schema.md` | Frequency, unit, provisional, citation |
| Airflow | `ingest_bi_seki` and `ingest_bps_stats`, weekly, `Layer.MARKET`: collect (SEKI: `bi-stats import`, the inbox) and export → `metamorph market load --publish` → discard. Compose services `bi-stats` and `bps-stats` |

Each source keeps its own figures. A GDP figure from SEKI and one from BPS are two datasets, never merged. An answer cites the one it uses.

### 3b, BPS: the website's own requests

**Decided by the project owner (2026-10-27): no registration.** The connector reads bps.go.id's public table pages, making the requests those pages make, by Phase 2's rules. It never uses a WebAPI key: none is issued to us, and a key found in a page is not ours to use. **Reuse is allowed:** the website's [terms](https://www.bps.go.id/id/term-of-use) give free use, commercial or not, with a citation naming the content's title, the access date and a link to it.

**What the site does (checked 2026-10-27, with a client naming itself):**
- **No `robots.txt`** (404). Cloudflare's bot management sits in front and may block "anomalies"; the pages were served without a challenge.
- **The table index** calls its own server action, `getListTable({locale, page, perpage})`, 100 per page: **2,628 national tables** in 27 requests, each with its ID, title, subject, first and last year, type, and **`last_update`**.
  - **1,758 dynamic tables** (type 2): about 17,700 table-years.
  - 722 static tables (type 1) and 148 of type 3: HTML layouts of their own, out of scope.
- **A dynamic table's page** (`/id/statistics-table/2/{id}/…`) is server-rendered with BPS's data object for the newest year: the variable (label, unit, subject, note), the rows (`vervar`, e.g. 38 provinces), the derived variable (`turvar`), the periods (`turtahun`: months, quarters, `Tahunan`) and the values (`datacontent`). It also lists the years held (`listTahun`).
- **Another year** comes from the page's own server action, `getDataTable({locale, id, year})`, one year per call. A call asking ten years answered only the first, so the connector asks one year at a time, as the page does.
- **Values are keyed by BPS's IDs:** each `datacontent` key is the row, variable, derived variable, year and period IDs, joined. The connector builds each key from the lists and reads it; it never splits a key.
- **The actions' IDs are build hashes** that change when BPS redeploys. The connector finds them by name (`getListTable`, `getDataTable`) in the scripts the pages load, as the browser does, and caches them by file name. If a name can't be found, the run stops: the page has changed.

**Collection:**
- **Weekly:** the index (27 requests), then only the dynamic tables whose `last_update` changed. For each, the page, then every year it holds. Revisions are counted.
- **The first collection is about 19,500 requests, about 11 hours** at one every two seconds. It resumes where it stopped: each year's answer is kept as it arrives.
- **A refusal stops the run:** an HTTP error, a challenge page, an answer of the wrong type, or an action that answers `status: false`.

**Series:**
- **Dataset:** one dynamic table, `bps:table:{var}`.
- **Series:** one row × one derived variable × one kind of period: `bps:table:1955:quarterly:vervar=100`. Each row and derived variable is keyed by BPS's IDs, never its labels.
- **Kinds of period by their labels:** month names → monthly; `Triwulan I`–`IV` → quarterly; `Semester 1`–`2` → semiannual; `Tahunan` → annual. **A table whose periods are none of these is noted, not guessed.**
- **The unit** is the variable's `unit`. BPS's notes (e.g. "2025: Angka sangat sementara") stay in `source_fields`; they are free text, and not read as provisional marks.
- **The citation** follows BPS's terms: the table's title, the access date and its link.

**A new repository, `BPS-Stats-Connector`** 0.1.0 (package `bps_stats`, command `bps-stats`), shaped like the others. Its tests replay pages, scripts and answers saved on 2026-10-27.

**The bundle carries only what changed.** BPS's published series would be millions of values, too many to re-send whole each week. A bundle may carry only some datasets, and the platform marks a series missing only when its dataset is re-sent without it (Phase 3: the platform).

## Phase 3: decisions

**Decided by the project owner (2026-10-27 and 28):**
1. **BPS is collected now, without registration,** from the website's own requests (3b above). The WebAPI and its terms are not used.
2. **All 108 SEKI tables.**
3. **SEKI by hand: a curator downloads each month's edition (option A, 2026-10-28).** On 2026-10-27 bi.go.id reset the connector's connections, though it served the same request from `curl` with the same User-Agent (Step 6). Nothing was tried to get past that. The options were:

   | Option | What |
   |---|---|
   | **A. A person downloads** ✓ | Each month a curator downloads the edition's zip (the 108 workbooks) from the SEKI page and drops it in `BI-Stats-Connector/data/inbox/`; `bi-stats import` reads it, and the weekly DAG imports the inbox |
   | B. Ask BI | Write to BI's statistics department (DSta-DQAD@bi.go.id) naming the connector, and collect automatically if BI agrees. `bi-stats collect` is kept for it |
   | C. Without SEKI for now | BPS's tables carry GDP and prices; money, credit, rates and the balance of payments wait |
   | D. The IMF's API (looked at, not chosen) | The IMF republishes what BI reports, through a public SDMX API without a key: money, central bank and banks' balance sheets, rates, exchange rates, reserves, the balance of payments. Its June 2026 M2 equals SEKI's to the digit. But it lags SEKI by one to three months, lacks SEKI's breakdowns, and commercial reuse needs the IMF's permission |

   The curation console is to show curators where to download the edition (*The curation console: market pages*).

**Decided in the plan:**
- **SEKI: current sheets only.** Earlier sheets wait for a need, like Phase 2's Step 10.
- **SEKI: the monthly zip,** since option A. Per-table downloads would arrive up to two weeks earlier, but bi.go.id refuses the connector.
- **BPS: dynamic tables only,** at the national domain. Static tables and regional domains wait for a need.
- **The contract grows in place at 1.0,** with optional fields only.

## Phase 3: steps

| # | Step | Done when |
|---|---|---|
| 0 ✓ | **Check before building (2026-10-27).** The SEKI page, `robots.txt`, conditional requests, September's 108 tables surveyed; BPS's terms and spec read | The survey above |
| 1 ✓ | Contract: periods by frequency (`2026-08`, `2026-Q2`, `2026-S1`, `2025`), `frequency`, `unit`, nullable `industry`, `provisional`, `source_table`; bundles of whole datasets (`snapshot: "datasets"`). The new fields are always written, so migration 0018 brings Phase 2's stored records up to them | 50 contract tests pass, including drift |
| 2 ✓ | `BI-Stats-Connector`'s skeleton and architecture test | `uv run pytest` and `bi-stats --help` work |
| 3 ✓ | SEKI's reading rules and series, from real tables. Two rules came from the survey of all 108: a year's own figure may stand after an empty spacer column; and **BI numbers some rows twice** (10 tables, e.g. I.4–I.9's rows 121–124), so a repeated number is keyed by its occurrence (`121`, then `121-2`) | 58 tests; the rules read 107 of 108 tables (3,743 rows, 319,026 values). V.18 is noted: in its hidden 2010 columns, the values sit one column left of their headers |
| 4 ✓ | Adapters: the SEKI page, conditional GET, a refusal; the `.xls` grid | Adapter tests, replayed from saved files |
| 5 ✓ | `collect`, the store, `export`, `status`, `health`, the CLI; the image `metamorph/bi-stats:dev` | A collected store exports a bundle whose every record `is_valid` |
| 6 ✓ | **The first collection, 2026-10-27: refused.** bi.go.id resets the connector's connections (twice on the SEKI page, `Errno 54`), while the same request from `curl` with the same User-Agent is served. A further check with other headers was stopped as circumventing a bot check. Nothing is worked around. **Option A, 2026-10-28:** `bi-stats import` reads an edition's zip, from a path or the inbox (`data/inbox/`), with the same `Collect` use case. A table's number comes from its file name (BI's scheme, true of all 108), its title from its heading, its section from its numeral. A table is dated by its zip entry, so an older edition never replaces a newer table | 67 tests; September's edition imports |
| 7 ✓ | Platform: migration 0018, partial bundles, frequency, unit, marks and citation in statistics and health, the read contract. **Run 2026-10-27 in a copy of the live database** (`metamorph_p3`):<br>• 0018 rewrote the 2,182 stored Phase 2 series;<br>• a SEKI bundle built, for this test only, from the survey's September workbooks loaded 6,919 series, and again all unchanged;<br>• published 185 datasets, 9,101 series, 410,236 observations in 53 s;<br>• `statistics bi:seki` ok (newest period ended 2026-09-30) | 765 database tests pass; the gates hold |
| 8 ✓ | Airflow `ingest_bi_seki` on the local stack, 2026-10-28, after a backup (`backups/2026-10-28-before-seki-import`):<br>• its collect is `bi-stats import`, of the inbox;<br>• September 2026's edition loaded 6,919 series and published 107 datasets (V.18 noted) in a minute;<br>• a second run read every table unchanged and loaded all 6,919 unchanged;<br>• health is ok, with the newest period ending 2026-09-30. August's M2 is published as provisional (`Aug*`) | The DAG tests pass; a `dags test` run loads and publishes |
| 9 | AWS | Deferred with Phases 1 and 2 |
| 10 ✓ | `BPS-Stats-Connector`: skeleton, the page's data object, keys built from BPS's lists, kinds of period (a parenthetical note, such as `Semester 1 (Maret)`, set aside); the adapter (the index, a table page, a year, the actions found by name in the page's scripts, a challenge or refusal), replayed from saved files | 45 tests |
| 11 ✓ | BPS `collect` (resumable, only changed tables, noted tables' pages asked again), `export --since` (whole datasets), `status`, `health`; the image `metamorph/bps-stats:dev` | A collected store exports a bundle whose every record `is_valid` |
| 12 … | **BPS's first collection, running since 2026-10-27.** bps.go.id serves the connector, but slowly: about 280 answers an hour, so the 17,700 table-years take days. Its server fails often, with a `504`, a `520` or a timeout every few minutes. **From 2026-10-28 a server failure is not a refusal:** the table is noted and asked again next run, keeping the years it has, and the run goes on. Three tables failed in a row stop it. A refusal (`403`, `429`, `503`, a challenge) still stops it. 117 tables were kept by then.<br>**Cross-checked against SEKI, 2026-10-28:**<br>• BPS's year-on-year inflation, January to September 2026 (table 2263, Indonesia), equals SEKI's VIII.1 row 39 in all nine months;<br>• BPS's GDP at current prices by expenditure for Q1 and Q2 2026 (table 1955, Rp 6,187,598.6 and 6,552,068.0 billion) equals SEKI's VII.3 row 12, which SEKI marks provisional | Every dynamic table read or noted |
| 13 … | Airflow `ingest_bps_stats` on the local stack. **2026-10-28: the 116 tables collected so far were exported and loaded live** (`metamorph market load --publish`, 34 s): 2,045 series, whole datasets. The `dags test` run waits for the backfill, since its collect would resume the same days-long collection | A `dags test` run loads and publishes |

## Phase 3: validation

**Gates:**
- **Every table read or noted,** the reason named.
- **Values match the releases** they come from, for the months and quarters cross-checked.
- **Periods and marks kept:** quarters and years as such, provisional marks carried through.
- **Phase 2's records still load unchanged** under the grown contract.
- **Operations:**
  - a second load is all unchanged;
  - a refusal stops the run;
  - an unchanged table is one `304`.

**Monitored, never blocking on its own:**
- revisions;
- relabelled rows;
- tables noted unreadable;
- a table that has stopped (IX.9 ends in June 2017).

## Phase 3: risks

| Risk | What happens | What to do |
|---|---|---|
| BI renumbers a table's rows | A series ID names another row than before | Each edition is consistent in itself. A changed label under a number is reported, and the series is checked by hand |
| BI changes a table's layout | The table is noted unreadable | It is asked again next run. A rule changes only if many tables change |
| A concept revision, like June 2025's | Values change, or a new sheet starts | The current sheet is what's published. Revisions are counted |
| A month's SEKI edition isn't downloaded | SEKI's figures age | `health` warns when no edition has been looked at for 14 days, or the newest period ended over 90 days ago. The console is to show where to download it |
| BI changes the edition's file names or zip layout | Tables are listed under other names or numbers | The import stops on a zip without `TABEL….xls`. A table's number is checked against the SEKI page when a curator reports a change |
| The bundle grows: about 310,000 values | A larger weekly bundle and publish | Workbooks are stored by sha256, and unchanged series load as unchanged. Observations go in by `COPY` |
| BPS's bot management blocks the connector | The run stops with exit 2 and a failed task | Nothing is worked around. SEKI still carries BPS's GDP and CPI. Registering for the WebAPI is the fallback |
| BPS's server fails often | Tables are noted "server failed" | They are asked again next run. Three in a row stop the run, and the next week resumes |
| BPS redeploys its site | The actions' IDs change | They are found again by name in the page's scripts. A name that's gone stops the run |
| BPS's volume: millions of values | Large bundles and publishes | Bundles carry only changed datasets. The publish is measured at Step 12 and made incremental if needed |

## The curation console: market pages (to design)

The [curation console](../../Metamorph-Curation-Web/README.md) has no market pages yet. What they must do is gathered here as it comes up, and settled when they are designed.

**1. Where to download SEKI's edition** (the project owner, 2026-10-28). Since option A, a curator downloads each month's SEKI edition by hand. To keep that easy to maintain, the console shows it beside the `bi:seki` source:
- **the addresses:** the [SEKI page](https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Default.aspx) and the edition's zip, `https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Documents/SEKI_SEPTEMBER_2026.zip` for September 2026 (published 15 October);
- **where the zip goes:** `BI-Stats-Connector/data/inbox/`, which Airflow's Monday run imports, or `bi-stats import` (the connector's README). An upload from the console itself is a later choice;
- **whether it's current:** the newest edition imported and the newest period, with `metamorph health`'s `statistics bi:seki`, so a missed month shows.

To decide then: the addresses are kept as data, for example beside `market.statistics_source`'s `bi:seki` row, so a curator can correct them without a deploy. The console reads them through the curation API, as it reads everything.

**Also to weigh then,** from what the plan already reports: tables noted unreadable (SEKI's V.18) or unanswered (BPS), SEKI rows relabelled under the same number, and market records in the review queue.
