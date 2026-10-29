# Plan: curation for the market data layer

**Status (2026-10-29): built and live.** The project owner took every recommendation (D1–D5) on 2026-10-29, on the condition that the build keeps to Clean Architecture; `tests/test_architecture.py` holds the dependency rule. Steps 0–7 are done, and AWS (Step 8) is deferred with the rest.
- **Platform:** migration 0022 (live, after a backup in `backups/2026-10-29-before-market-curation`); `domain/market/curation.py`, the shared link resolution in `domain/market/links.py`; `CurateMarket`, `RelinkMarket` and the market read models; 11 reads and 6 changes under `/api/v1/market/`. 873 tests pass.
- **Console:** a Market section in the navigation (sources and links, companies, statistics, reports, press releases) and on the Overview. 119 unit tests and 33 end-to-end tests pass, 4 of them the market's.
- **On the live data:** a links-only publish takes 13–22 ms; a full publish after the refactor is identical, table for table, but for `published_at`; each market page's query answers in at most about 100 ms.
- **Not done by design:** no sector exists yet. Sectors are for curators to define, from the Sources and Links page.

**Outcome:** curators see the market layer in the console. They keep its curated links (registers, industries, statistics sources) without a migration, and each change is audited and published at once. **Out of scope:** correcting market records themselves (deferred, see *Later: correcting market records*), and uploading SEKI's edition from the console.

## Context

**The market registry is the market's system of record** ([market-data-layer-plan.md](market-data-layer-plan.md)). Five connectors load it, and `market_publish` rebuilds `published_market` from it ([dags/README.md](../dags/README.md)). On 2026-10-29 it held:

| Kind | Table | Rows |
|---|---|---|
| Licensed entities | `market.entity` | 243 |
| Series | `market.series` | 238,601 |
| Reports | `market.report` | 13 |
| Press releases | `market.release` | 1,178 |
| Registers | `market.register` | 1 |
| Industries | `market.industry` | 4 (all from `ojk:portal`) |
| Statistics sources | `market.statistics_source` | 3 |

**Today, curation reaches the market in only one way.** A record the contract rejects is quarantined and opens a `quarantine` item in `curation.review_item`, which the console's Review page lists. Apart from that:
- **The curated links are seeded by migrations** (0016, 0017, 0020): each register's and industry's regulations and reports, and each source's citation and freshness. Changing one needs a new migration and a deploy.
- **The console has no market pages** ([Metamorph-Curation-Web](../../Metamorph-Curation-Web/README.md)). What they must do is gathered in the market plan's section *The curation console: market pages*: where to download SEKI, a reader for reports, and the market's notes.

**The regulation layer's curation is the model to follow** ([curation-workflow-design.md](curation-workflow-design.md), [curation-web-separation-design.md](curation-web-separation-design.md)):
- **Overlays, never edits:** corrections, suppressions, approvals, text corrections and assigned IDs sit on top of source values.
- **Every action needs a reason** and is audited (`curation.audit_log`) in the same transaction as the change.
- **Republished at once:** each action is published before the API answers (ADR-6).
- **One way in:** the API is the only writer. The console reaches it through its OpenAPI contract, which is checked in CI.

**Why now:**
1. **SEKI needs a curator every month.** From about 15 November, a curator downloads BI's edition by hand (Phase 3, option A). The console must show where to download it and whether the newest edition is in.
2. **The retrieval layer depends on the curated links.** `industry_context` joins a market question to the law through them ([retrieval-tools-design.md](retrieval-tools-design.md)). They must be easy to keep right, and its open question 2 asks for one list of industries across sources.
3. **Curators can't see the market data,** or the notes it carries.

## Principles applied

- **The connectors stay the source of market records.** Curation never edits a record they sent.
- **Curated links are reference data no connector writes.** From now on, curation actions write them. Migrations stop adding links and only change the schema.
- **Count the cost** ([engineering-principles.md](engineering-principles.md)). Build what is needed now: reads, and curating the links. Correcting market records waits for a measured need.
- **Checks warn.** A link to a regulation or report not published yet is accepted with a warning. It links nothing until that document is published, as links to unpublished reports already behave.
- **One owner each.** Domain rules decide what a link may be. The API is the only writer. The console shows data and calls actions.

## What curators get

### 1. See the market (read only)

| Page | What a curator sees |
|---|---|
| **Overview** `/` (a market section) | Each market source's health, last load and newest period. Counts of companies, series, reports and releases, and open market review items |
| **Sources** `/market/sources` | Each register and statistics source: freshness, citation, curated links, newest edition or period. **For `bi:seki`:** where to download the edition, where the zip goes (`BI-Stats-Connector/data/inbox/`), the newest edition imported and its newest period (requirement 1) |
| **Companies** `/market/companies?q=&register=&status=&business_type=` | The register's companies, with their licences and registrations, history on the list, review notes, and the releases that name them |
| **Statistics** `/market/datasets?q=&source=&industry=` | Datasets with their industry, links, series count and span. A dataset's series, and a series' observations with their provisional marks |
| **Reports and releases** `/market/reports`, `/market/releases?q=&from=&to=` | A report or release and its passages, with pages, and the regulations and companies each passage names (requirement 2) |
| **Review** `/review?kind=quarantine` (as today) | Market quarantine items named by record kind and ID, beside the regulation items |

### 2. Keep the curated links

| What | Fields | Where it is kept | What a change does |
|---|---|---|---|
| A register | `governed_by[]`, `reports[]`, `fresh_days` | `market.register` | Updates the register, its companies' regulations, and the industries on it |
| An industry | per `(source, name)`: `register`, or `governed_by[]`; `reports[]`. Add or remove one | `market.industry` | Updates the industry and every dataset of that industry: `register`, `governed_by[]`, `reports[]` |
| A statistics source | `citation`, `fresh_days`; for SEKI, `download_page` and `download_hint` (new) | `market.statistics_source` | Updates citations and health's freshness threshold. The download fields are shown on Sources |

Each change takes a reason, is audited, and is published before the API answers.

### 3. One list of industries (decision D3)

`market.industry` is keyed by each source's own names, so "Bank Umum Syariah" is an OJK portal name, and SEKI and BPS have none. `industry_context` wants one curated industry, such as "sharia fintech lending", that gathers each source's names, the register and the reports.

**Proposal:**
- **A new table, `market.sector`:** `id` (e.g. `sharia-fintech-lending`), `name` in Indonesian and English, and its member industries (`market.industry` rows).
- **Published as `published_market.sector`.**
- **Curated on the same pages.**

It is the one new piece of data in this plan, so the owner decides whether it is built here or with the retrieval layer.

### Later: correcting market records

This is recorded, not built. It should be built when a curator finds an error the connector can't fix, such as a company name OJK misprinted or a series label.
- **The design:** an override keyed by `(kind, record_id, field)`, applied by `publish_market`'s domain functions. Also a suppression of a record, and a conflict when the source later changes a corrected field, as for documents.
- **Until then:** errors are fixed in the connector, or recorded.

## Design

### Where the links live (decision D1)

- **Option A (recommended): they stay in `market.register`, `market.industry` and `market.statistics_source`.** Only curation use cases write them, and those use cases audit to `curation.audit_log`, signed by a `curation.curator`. No connector writes these tables, so nothing undoes a change.
- **Option B: move them into the `curation` schema as overlays.** This needs more migrations and changes what the publish reads, for no gain while no source sends links.

### Publishing a change at once (decision D2)

A regulation action is published before the API answers (ADR-6). A full market publish takes about 3.5 minutes on 238,601 series, which is too slow for a request.

**Proposed: a links-only publish (`RelinkMarket`).** It recomputes only what links decide:
- `register.governed_by` and `reports`;
- each dataset's `register`, `governed_by` and `reports`, from its `(source, industry)`;
- the industries and sectors.

It runs in the same transaction as the change and its audit row, so `published_market` never disagrees with the record of a change. It uses the same domain functions as the full publish: today's link resolution inside `statistics._dataset` and `with_links` is pulled out into one function that both call. **The target is under a second.**

**Rejected:** leaving the change for the next `market_publish` run. It could stay unpublished for a week.

### The layers

- **Domain** (`domain/market/curation.py`, pure):
  - a regulation reference must be a canonical ID (`metamorph_contract.is_canonical`);
  - a report reference must be a report ID or a family (`ojk:lpksi`);
  - an industry has a register or regulations of its own;
  - `fresh_days` must be positive;
  - a reason is required.
- **Domain** (`domain/market/links.py`): the link resolution pulled out as above.
- **Application:**
  - `CurateMarket`: set a register's links, set or remove an industry, set a source;
  - `RelinkMarket`;
  - the market reads, `MarketViews`, for the API.
  
  Ports: `MarketCurationActions` (write and audit, one transaction) and `MarketViewSource`.
- **Adapters:**
  - PostgreSQL;
  - the API's `/market/…` routes;
  - the OpenAPI contract, regenerated and checked by `tests/test_api_contract.py`.
- **Console** (`Metamorph-Curation-Web`):
  - types regenerated (`npm run api:types`, `api:check` in CI);
  - pages under `src/app/(console)/market/`;
  - views in `src/components/`, and changes through server actions that call one API action each, as today.

### The API (sketch)

| | Endpoint | What |
|---|---|---|
| Read | `GET /market/overview` | Health, counts and newest periods per source; open review items |
| Read | `GET /market/sources`, `GET /market/sources/{id}` | Registers and statistics sources with their links |
| Read | `GET /market/companies`, `GET /market/companies/{id}` | Filtered and paged; a company with its records, history and mentions |
| Read | `GET /market/datasets`, `GET /market/datasets/{id}`, `GET /market/series/{id}/observations` | The catalog, a dataset's series, a series' figures |
| Read | `GET /market/reports/{id}`, `GET /market/releases`, `GET /market/releases/{id}` | Cards and passages with their mentions |
| Act | `PUT /market/registers/{id}/links` | `governed_by[]`, `reports[]`, `fresh_days`, `reason` |
| Act | `PUT /market/industries/{source}/{name}`, `POST …/withdraw` | Set or remove an industry, with a reason |
| Act | `PUT /market/sources/{id}` | `citation`, `fresh_days`, the download fields, `reason` |

An action answers with the record as published, and any warnings ("ojk:pojk:2026:9 is not published yet").

### Two publishes at once

A curator may change a link while the Monday `market_publish` is rebuilding. Today the full publish reads the links before its transaction, so it would write the old links over the new ones. **The fix:**
- the full publish reads the links inside its transaction;
- the full publish and `RelinkMarket` take one advisory lock, `published_market`'s;
- a link change during a full publish waits for it to finish. That can happen only in the weekly publish window.

## Steps

| # | Step | Done when |
|---|---|---|
| 0 ✓ | The owner's decisions D1–D5 | Recorded in this plan |
| 1 ✓ | Domain: the link rules. The link resolution pulled out of `statistics._dataset` and `with_links` into one function (a refactor) | Tests first. A full publish of the live data is identical, by the 2026-10-29 fingerprint ([market-data-layer-plan.md](market-data-layer-plan.md), Phase 3 risks) |
| 2 ✓ | Reads: `MarketViews`, the API's read endpoints, the contract | API tests, unit and against PostgreSQL. `test_api_contract.py` passes |
| 3 ✓ | Console read pages: the Overview section, Sources (with SEKI's download, seeded by a migration for now), Companies, Statistics, Reports and releases. The Review page names market items | Vitest for the presentation rules, one Playwright flow. Each page shows the live data. **Wanted before SEKI's October edition, about 15 November** |
| 4 ✓ | Curating links: `CurateMarket`, `RelinkMarket`, the advisory lock, the API's actions | A change is validated, audited, and relinked in one transaction in under a second. Relinking and a full publish give identical rows |
| 5 ✓ | Console forms: a register's links, an industry, a source (SEKI's download fields included) | One Playwright flow: change a link with a reason, see it published and in the audit log |
| 6 ✓ | If D3 is yes: `market.sector`, published and curated | `industry_context`'s join is one curated row per sector |
| 7 ✓ | Docs: [published-market-schema.md](published-market-schema.md) (sectors, if built), the curation docs, both READMEs. The market plan's console section points here | Reviewed |
| 8 | AWS | Deferred with the rest |

## Validation

**Gates:**
- **A change is published at once,** audited with its reason, and visible on its page.
- **Relinking and a full publish agree,** row for row.
- **The regulation layer's curation is unchanged:** every existing test passes.
- **The contract holds:** `test_api_contract.py` in the platform and `npm run api:check` in the console.
- **One way in:** the console writes only through API actions, and no migration writes links any more.

**Monitored, never blocking on their own:**
- curation actions on the market, by kind;
- open market review items;
- links naming documents not published.

## Risks

| Risk | What happens | What to do |
|---|---|---|
| Relinking and the full publish resolve links differently | A dataset's regulations change at the next weekly publish | One domain function for both, and a test that they agree |
| A link change during a full publish | The change is overwritten by the old links | The links are read inside the publish's transaction, under one advisory lock (above) |
| A wrong regulation or report ID | A dataset links the wrong law, or nothing | Form checks; a warning for an ID not published; the change shown at once with what it now links |
| The market pages grow into a second app | More code than the need | Read pages over the read contract only. Corrections to records wait (*Later*) |
| SEKI's download address changes | Curators look in the wrong place | It is data on the source, which a curator corrects without a deploy |

## Decisions for the project owner

- **D1. Where the curated links live.** Recommended: in the `market` tables, written only by curation actions (option A).
- **D2. Publishing a link change at once,** by a links-only publish. Recommended: yes.
- **D3. One list of industries across sources (`market.sector`).** Here (Step 6), or with the retrieval layer. Recommended: here, since the console is where it is kept.
- **D4. SEKI's download information as data on the source,** shown and editable. Recommended: yes. Upload from the console stays a later choice.
- **D5. Who curates the market.** Today's curators, with the same rights (`curation.curator` has no roles). Recommended: yes, until a need for roles appears.

## Critical files

| Repository | Files |
|---|---|
| Platform | `domain/market/links.py`, `domain/market/statistics.py`, new `domain/market/curation.py`; `application/publish_market.py`, new `application/curate_market.py`, `application/views.py`; `adapters/postgres/market.py`, `adapters/api/app.py`; a migration for the download fields (and `market.sector`, if D3); `docs/api/openapi.json` |
| Console | `src/lib/api/` (regenerated `schema.d.ts`, reads, `perform()`), `src/app/(console)/market/`, `src/components/`, `e2e/` |
