# Retrieval tools: design (draft)

**Status: draft, 2026-10-28.** For review by the team building the Knowledge & Retrieval layer and the team building the answering agent. Nothing here is built yet.

**2026-10-30:** [retrieval-architecture.md](retrieval-architecture.md) splits this layer into providers (market: ours; regulatory: Friend 2's) behind a shared contract and a gateway. The tools, principles, legal force and evaluation below still hold; that page says who owns each part, and proposes renaming `get_provision` to `read`.

**Decided by the project owner on 2026-10-28, and built into this draft:**
- **The answering agent is not ours.** We build a retrieval layer that exposes its capabilities as tools. An answering agent calls them, orchestrates them, and writes the final response.
- **Reports are a module of their own, in the market layer.** OJK's and BI's reports and roadmaps (LPKSI, KEKSI, RP3SI, …) are kept out of the regulation layer, published as `published_market.report` and `report_passage` ([market-data-layer-plan.md](market-data-layer-plan.md), Phase 4). Behind the tools, the agent still has one text search over regulations and reports.
- **OJK's LPKSI listing is synced** by the reports connector. Other reports are imported by hand.
- **OJK's press releases since 2020 are a record kind of their own** (`published_market.release` and `release_passage`, Phase 5), kept by the same connector. The regulations and companies each report or release passage names are published as `published_market.mention`.

## Where it sits

```
 Connectors ─► Platform ─► published         (legal documents: regulations, fatwas)
                       └─► published_market  (registers, companies, statistics; reports, releases, their passages
                                              and what they name)
                                  │  read only
                                  ▼
             Retrieval layer (this design; its own repository)
               retrieval schema: embeddings, kept current from published.change_log
               tools, served over MCP
                                  │  tool calls
                                  ▼
             Answering agent (another team): plans, calls tools and its own web search, writes the answer
```

- **The retrieval layer reads only the two read contracts:** [published-schema.md](published-schema.md) and [published-market-schema.md](published-market-schema.md). It writes only its own `retrieval` schema, in the same PostgreSQL (pgvector is installed there and unused).
- **News is the agent's,** searched on the web at question time. The platform never stores it ([market-data-layer-plan.md](market-data-layer-plan.md), Context).

## Principles

1. **Evidence, not answers.** A tool returns what the sources say, structured and citable: a passage with its address and pages, a figure with its period and unit. It never summarises or concludes; that is the agent's job. A summary would hide the evidence the agent must cite.
2. **Weight travels with the evidence.** We don't control the agent's prompt. So every result says how much it counts: its legal force, status, validity, provisional mark and as-of date. An agent that reads only the fields still tells a rule from a roadmap.
3. **A few tools, one job each.** Seven tools cover both layers (below). One search covers every text: regulations from the regulation layer, reports from the market layer, each from its own index.
4. **Deterministic.** No generative model runs inside a tool: only embeddings and, if it earns its place, a reranker. The same call gives the same result, so the tools can be tested, cached and cheap. The agent can change without the tools changing.
5. **Bounded output.** Results are paged and capped, and their fields are short, so one call never floods the agent's context.
6. **The tool descriptions are the API.** For an agent, the descriptions are all it reads. Each says what the tool is for, when to use it, and what each field means, legal force included.
7. **Contracts are versioned.** A tool's input and output schemas carry a version. A breaking change is a new version, served beside the old one until the agent moves.

## The tools

| Tool | Answers | Reads |
|---|---|---|
| `search_documents` | Which passages of regulations, fatwas, reports or press releases speak to this? | `published.provision_unit`, and `published_market.report_passage` and `release_passage`, through two indexes |
| `get_provision` | The whole article, a document's outline, or a report's or a release's passage in context | `published.document`, `provision`; `published_market.report`, `report_passage`, `release`, `release_passage` |
| `follow_links` | What amends, revokes, implements or cites this, and what it rests on; which reports and releases name it | `published.edge`, `status_event`; `published_market.mention` |
| `find_series` | Which statistics measure this? | `published_market.dataset`, `series` |
| `get_observations` | The figures of these series over these periods | `published_market.observation` |
| `find_companies` | Who is licensed, registered or gone, and since when; what OJK announced about them | `published_market.company`, `entity`, `register`; `mention`, `release` |
| `industry_context` | For an industry: its registers, governing regulations, reports and datasets | `published_market.sector` and `industry` |

### `search_documents`

**Input:**
- `query`: the question, in Indonesian or English;
- filters, all optional:
  - `kind[]`: `law`, `regulation`, `implementing_rule`, `fatwa`, `guideline`, `circular`, `explanatory`, `report`, `release`;
  - `issuer[]`, `family[]`, `document_ids[]` (for example, the regulations `industry_context` named);
  - `in_force_on`: a date. It keeps documents in force on that day and units whose `valid_to` is later;
  - `published_from`, `published_to`: dates. They keep reports and releases published between them ("what did OJK announce this year");
  - `legal_force[]`;
- `limit` (default 8, at most 25), `cursor`.

**Each result:**
- `ref`: a stable key to cite and to pass to other tools, e.g. `doc:ojk:pojk:2024:40#pasal-5/ayat-1`, `report:ojk:lpksi:2025#p-12`, or `release:ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital#p-1`;
- `citation`, e.g. `POJK 40 Tahun 2024, Pasal 5 ayat (1)`, `LPKSI 2025, hlm. 31–32`, or `Siaran Pers OJK SP 188/DKPU/OJK/X/2026, 8 Oktober 2026`;
- `title`, `heading_path`, `wording` (the unit's words, capped), `pages`;
- `kind`, `legal_force`, `status`, `effective_on`, `valid_to`, `under_review`;
- `score`, and `matched_by` (`semantic`, `words`, or both).

**How it ranks:**
- **Two indexes, one tool.** Legal units are indexed apart from report and release passages, each through its own adapter, with the same embedding conventions and the same `ref` and result shapes. A `kind` filter selects either one; without it, both are searched and their rankings fused. A report or release passage always carries `legal_force: none`.
- **Hybrid search in each.** Embeddings and full-text matching, fused by reciprocal rank fusion. For legal units, the embedding input is the one the read contract recommends (`"{citation}, {heading_path}\n{wording}"`). For report passages, it is `"{report} ({issuer}), hlm. {pages}\n{text}"`; for release passages, `"{citation}: {title}\n{text}"`.
- **Filters first, ranking second,** both in SQL, so a filter never empties a page of results after the fact.
- **Optional reranking** by a cross-encoder, kept only if the evaluation set shows it helps.

### `get_provision`

**Input:** a `ref`.
- **A legal document's `ref`** returns its card (citation, title, kind, status, dates, legal force) and its outline to two levels.
- **A provision's `ref`** returns its full wording, its children, its elucidation (`penjelasan/…`) if published, and the provisions it refers to.
- **A report's `ref`** returns its card (title, issuer, edition, published date, pages, passages); **a release's `ref`** returns its card (title, number, date, citation, passages). **A passage's `ref`** returns the passage with the passages either side of it.

### `follow_links`

**Input:** a `ref`; `direction` (`outgoing`, `incoming`, or both); `types[]` from the contract's vocabulary: `legal_basis`, `implements`, `amends`, `supersedes`, `revokes`, `partly_revokes`, `adopts_fatwa`, `changes_fatwa`, `refers_to`.

**Each result:** the link's type, both ends as `ref`s with their citations, `effective_on` and `confidence`. Then the document's `status_event` history, so "is this still the rule?" is one call.

**Named by:** with `named_by = true`, also the report and release passages that name a regulation (`published_market.mention`), newest first, as passage `ref`s with their citations and dates. A mention means "names": the passage's words say whether it announced, explained or merely cited the regulation. A release announcing a regulation is not the regulation.

### `find_series`

**Input:** `query` (e.g. "pembiayaan LPBBTI syariah outstanding"); optional `source[]` (`ojk:portal`, `bi:seki`, `bps:table`), `industry`, `frequency`; `limit`, `cursor`.

**Each result:** `series_id`, `label` (the measure and its members), `dataset`, `metric`, `group`, `industry`, `unit`, `frequency`, `first_period`, `last_period`, the source's `citation` and the dataset's `url`.

**How it ranks:** hybrid search over each series' label with its dataset's metric and group. The catalog is tens of thousands of labels, and nothing else: values are never embedded.

### `get_observations`

**Input:** `series_ids[]` (at most 20), `from`, `to` (periods: `2026-08`, `2026-Q2`, `2025`).

**Each observation:** `period`, `value` (as the source gives it, never rescaled), `provisional`. **Per series:** `unit`, `frequency`, the source's `citation`, `as_of` (the dataset's `updated`), `published_at` and `url`. BPS's terms ask that a figure be cited with the table's title, the access date and a link, and those three fields carry that.

### `find_companies`

**Input:** optional `register`, `query` (a legal or platform name), `status` (`licensed`, `registered`, `left`), `business_type` (`sharia`, `conventional`); `limit`, `cursor`.

**Each result:** the company with its `legal_name`, other `names`, `status`, `business_type`, `first_listed` and `left_after`. Then its records: each license or registration (`kind`, number, date), and its `review_notes`. With `history = true`, also the editions that listed it. With `announcements = true`, also the release passages that name it by its legal name, newest first: an official date and OJK's own words (a revocation, a sanction) beside the register's "left the list".

### `industry_context`: where the two layers meet

**Input:** an `industry` ID, or a `query` such as "sharia fintech lending".

**Output:**
- the industry;
- its registers;
- its governing regulations, as document `ref`s with citations and status;
- its reports, as document `ref`s;
- its datasets, with `last_period`.

These links are curated by the Metamorph team, never inferred. That makes the join from a market question to the law exact: "sharia fintech lending" → the register `ojk:lpbbti` → POJK 40/2024 and SEOJK 19/2025 → the LPBBTI roadmap. The agent then searches within those regulations (`search_documents` with `document_ids`) rather than hoping a semantic search lands on them.

## Legal force

Derived by the retrieval layer, from `document.kind` for legal documents and from the table for everything else, so the agent never has to know the platform's kinds:

| `legal_force` | Kinds | What an answer may say |
|---|---|---|
| `binding` | `law`, `regulation`, `implementing_rule` | What is required, citing the provision and its validity |
| `sharia` | `fatwa`, `guideline`, `circular` (DSN-MUI) | What sharia principles require. A regulation that adopts a fatwa makes it binding (`adopts_fatwa`) |
| `explanatory` | `explanatory` | How the issuer explains a rule; never the rule itself |
| `none` | Report and release passages, and every statistic and company record | What a regulator reports, plans, announces or counts. Never a requirement |

Every result also carries what qualifies it:
- **For documents:** `status`, `valid_to` and `under_review`.
- **For statistics:** `provisional` and `as_of`.

## Interface

- **MCP** is the primary interface: each tool with its JSON Schema and description, so any agent framework can call it. The same use cases sit behind an HTTP API for tests and other clients.
- **Results are JSON.** Errors are typed: unknown `ref`, a filter with no match, a limit exceeded. "Nothing found" is an empty result, never an error.
- **Access.** The read contracts already hold only content we may serve (`public` or `licensed`). The tools add authentication of the agent, and a log of each call (tool, input, result refs) to audit and to build the evaluation set from.

## Shape of the repository

As the connectors and the platform: Clean Architecture, with an architecture test that keeps dependencies pointing inward.
- `domain/`: evidence types, `ref`s, legal force, citations, fusion of rankings;
- `application/`: one use case per tool; ports for the read contracts, the index, the embedder;
- `adapters/`:
  - PostgreSQL (the read contracts, and the `retrieval` schema);
  - the embedding model;
  - the indexer, which follows `published.change_log` and the market schema's `published_at`;
  - MCP and HTTP.

## Evaluation

The retrieval layer is judged on its own, apart from the agent's answers. That way "retrieval missed it" and "the agent misread it" can be told apart when two teams own the two halves.
- **A set of test questions with expected evidence,** per phase of the customer journey. Each question names the `ref`s, series or companies it should find:

  | Journey phase | Example question | Expected |
  |---|---|---|
  | 1. Macro research | How fast is sharia financing growing against GDP? | SEKI's GDP series, OJK's sharia financing series |
  | 2. Industry research | How many sharia P2P lenders are licensed, and what does OJK plan for them? | `find_companies` on `ojk:lpbbti`; the LPBBTI roadmap's passages on its direction |
  | 3. Product | Which akad may a sharia P2P product use? | The DSN-MUI fatwa on online financing and the regulation adopting it |
  | 4. Compliance and entry | What does a new P2P lender need to be licensed? | POJK 40/2024's licensing articles, in force |

- **Measures:**
  - for the searches: recall within the first 8 results, and the reciprocal rank of the first expected result;
  - for the exact tools: whether they return exactly the expected records.
- **When it runs:** on every change to the parser, the data, the index or the ranking. The platform's gates ([engineering-principles.md](engineering-principles.md)) apply: a few gates tied to retrieval, everything else monitored.
- The answering team owns the evaluation of answers; both teams grow the question set.

## One question, end to end

*"Is sharia P2P lending worth entering, and what does it take?"* An agent might call:
1. `industry_context("sharia fintech lending")` → `ojk:lpbbti`; POJK 40/2024 and SEOJK 19/2025; the LPBBTI roadmap; the portal's LPBBTI Syariah datasets.
2. `find_series` within those datasets, then `get_observations` for outstanding financing, three years by month: growth, with provisional marks.
3. `find_companies(register: ojk:lpbbti, business_type: sharia, announcements: true)` → who is licensed, who entered, who left, and what OJK announced about those who left.
4. `search_documents("persyaratan perizinan penyelenggara", document_ids: the regulations, in_force_on: today)` → the licensing articles.
5. `follow_links` on them, to confirm nothing amends them since.
6. `search_documents("arah pengembangan LPBBTI syariah", kind: report)` → the roadmap's direction, with `legal_force: none`.
7. `search_documents("pendanaan bersama syariah", kind: release, published_from: a year ago)` → what OJK announced lately, dated.

The agent writes the answer from these results, citing each `ref` and series, and adds news from its own search.

## What the platform must add

| Piece | Why | Where |
|---|---|---|
| Reports and their passages: `published_market.report`, `report_passage` | Reports in `search_documents` and `get_provision` | [market-data-layer-plan.md](market-data-layer-plan.md), Phase 4 |
| `published_market.industry`: each curated industry with its registers, regulations, reports and datasets | `industry_context` | **Done** (Phase 4, Step 6, migration 0020) |
| `published_market.sector`: one curated industry across the sources' names, with what its industries link | `industry_context`'s starting point | **Done** (migration 0022, [market-curation-plan.md](market-curation-plan.md)); curators define the sectors |
| `reports[]` on `published_market.register` and `dataset`; a report's `discusses[]` | Reports from the market side, and from a report to the regulations it discusses | `reports[]` **done** (migration 0020). `discusses[]` is curation's; mentions (below) give the regulations a passage names |
| Releases and their passages: `published_market.release`, `release_passage` | Releases in `search_documents` and `get_provision` | **Done** (Phase 5, migration 0021) |
| `published_market.mention`: the regulations and companies each report or release passage names | `follow_links` with `named_by`; `find_companies` with `announcements` | **Done** (Phase 5, migration 0021) |

## Open questions

1. **The embedding model and where it runs.** It must handle Indonesian legal text well, and Arabic for fatwas would be a bonus. It runs locally first and on AWS later (deferred). To choose by the evaluation set, between a hosted multilingual model and an open one.
2. **One list of industries across sources.** *Settled 2026-10-29:* `published_market.sector` is one curated industry (e.g. `sharia-banking`) gathering each source's names, with what they link ([market-curation-plan.md](market-curation-plan.md)). Curators define the sectors in the console; none exists yet.
3. **The `sharia` force of a fatwa** that no regulation adopts. Is it `sharia` or `guidance`? For the project owner, with legal advice.
4. **Report passage size,** from Phase 4's Step 0b, and whether reports need a heading-aware split later (a general option in `metamorph-pdf-text`).
5. **A read-only SQL tool over a few market views,** for analysts' questions the seven tools don't cover. It waits for a need: open-ended SQL is harder to test and to guard.
6. **Where the retrieval layer is hosted,** and how the agent authenticates. With the AWS deployment, deferred.
