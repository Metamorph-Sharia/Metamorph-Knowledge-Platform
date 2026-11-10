# Retrieval tools: design (draft)

**Status: draft 2026-10-28; built and deployed, 2026-11-03.** For review by the team building the Knowledge & Retrieval layer and the team building the answering agent.

**2026-10-30:** [retrieval-architecture.md](retrieval-architecture.md) splits this layer into providers (market: ours; regulatory: Friend 2's) behind a shared contract and a gateway. The tools, principles, legal force and evaluation below still hold; that page says who owns each part, and proposes renaming `get_provision` to `read`.

**As built, 2026-11-04.** The gateway in `Metamorph-Retrieval` serves these tools over MCP, as tool catalog 0.1. It runs on AWS as the ECS service `retrieval-gateway` ([deploying.md](../../Metamorph-Retrieval/docs/deploying.md)). Where the build departs from this design, an **As built** note says so. In short:
- **Seven tools, one renamed, one added.**
  - `get_provision` is now `read`.
  - The regulation provider adds `find_provision`, which resolves a citation to its provision.
- **`search_documents` searches regulations, fatwas, reports and releases together.** The gateway fuses the two providers' rankings, then reranks the candidates with a cross-encoder.
- **`follow_links` answers for both layers, merged.**
- **Open:** how an agent authenticates to the production gateway, and exporting the traces.

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
- **As built:** each provider has its own schema: `retrieval_market` and `retrieval_regulation`. Neither index follows `published.change_log` yet. Each is rebuilt as a new index version and activated only when the evaluation set passes. The market's refresh has a DAG, which is paused; the regulation index is built by hand.

## Principles

1. **Evidence, not answers.** A tool returns what the sources say, structured and citable: a passage with its address and pages, a figure with its period and unit. It never summarises or concludes; that is the agent's job. A summary would hide the evidence the agent must cite.
2. **Weight travels with the evidence.** We don't control the agent's prompt. So every result says how much it counts: its legal force, status, validity, provisional mark and as-of date. An agent that reads only the fields still tells a rule from a roadmap.
3. **A few tools, one job each.** Seven tools cover both layers (below), and `find_provision` was added in the build. One search covers every text: regulations from the regulation layer, reports from the market layer, each from its own index.
4. **Deterministic.** No generative model runs inside a tool: only embeddings and, if it earns its place, a reranker. The same call gives the same result, so the tools can be tested, cached and cheap. The agent can change without the tools changing. *The reranker earned its place (see Evaluation).*
5. **Bounded output.** Results are paged and capped, and their fields are short, so one call never floods the agent's context.
6. **The tool descriptions are the API.** For an agent, the descriptions are all it reads. Each says what the tool is for, when to use it, and what each field means, legal force included.
7. **Contracts are versioned.** A tool's input and output schemas carry a version. A breaking change is a new version, served beside the old one until the agent moves.

## The tools

| Tool | Answers | Reads |
|---|---|---|
| `search_documents` | Which passages of regulations, fatwas, reports or press releases speak to this? | `published.provision_unit`, and `published_market.report_passage` and `release_passage`, through two indexes |
| `read` (was `get_provision`) | The whole article, a document's outline, or a report's or a release's passage in context | `published.document`, `provision`; `published_market.report`, `report_passage`, `release`, `release_passage` |
| `find_provision` (added in the build) | Which provision does this citation name? | The regulation index |
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

**As built:**
- **The filters are named in the plural:** `kinds`, `issuers`, `documents`, `legal_force`, `in_force_on`, `published_from`, `published_to`. `family` was not built.
- **`sort`** (`relevance` or `newest`) is added.
- **Report- and release-only filters warn on regulations.** `published_from`, `published_to` and `sort` apply to reports and releases. On regulations, they are ignored with a warning.
- **`in_force_on` keeps a unit only if all three hold:**
  - its document is in effect by that day;
  - the unit's `valid_to` is later;
  - its document is not revoked by then. A revocation counts from the earliest dated whole-document `status_event`.

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

**As built:**
- **A regulation hit is a retrieval unit:** a `published.provision_unit`, normally an ayat with its huruf and angka items inside it.
  - Every provision can be read, but only units are searched. An article and its own paragraphs no longer compete for the same places.
- **A hit shows at most 3,000 characters of a unit's wording,** with a warning when it is shortened; `read` returns the whole unit. A long unit, such as an SEOJK chapter, would otherwise push a page past the gateway's 100 kB answer budget.
- **Word search in the regulation index** uses PostgreSQL's `indonesian` configuration.
  - A word held by more than 5% of the units still counts towards a hit's score, but doesn't choose which units are considered.
  - Meaning search is bge-m3 over pgvector HNSW.
  - The provider fuses the two by RRF.
- **The gateway fuses both providers' pages by RRF.** It then reranks the first candidates with `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`: 50, set by `METAMORPH_RETRIEVAL_RERANK_CANDIDATES`.
  - If the reranker is late (5 s) or fails, the fused order is returned with the warning `NOT_RERANKED`.

### `read` (was `get_provision`)

**Input:** a `ref`, and `window` (passages either side).

**As built:**
- **The market's refs:** reports, releases, their passages, companies and datasets are read as designed, with `window` for passages.
- **The regulations' refs:**
  - a document's `ref` returns its card with its `status_history`, but not its outline yet;
  - a provision's `ref` returns its whole wording.
  - Its children, its elucidation, the provisions it refers to, and `window` are not served yet.

**As designed:**
- **A legal document's `ref`** returns its card (citation, title, kind, status, dates, legal force) and its outline to two levels.
- **A provision's `ref`** returns its full wording, its children, its elucidation (`penjelasan/…`) if published, and the provisions it refers to.
- **A report's `ref`** returns its card (title, issuer, edition, published date, pages, passages); **a release's `ref`** returns its card (title, number, date, citation, passages). **A passage's `ref`** returns the passage with the passages either side of it.

### `follow_links`

**Input:** a `ref`; `direction` (`outgoing`, `incoming`, or both); `types[]` from the contract's vocabulary: `legal_basis`, `implements`, `amends`, `supersedes`, `revokes`, `partly_revokes`, `adopts_fatwa`, `changes_fatwa`, `refers_to`.

**Each result:** the link's type, both ends as `ref`s with their citations, `effective_on` and `confidence`. Then the document's `status_event` history, so "is this still the rule?" is one call.

**Named by:** with `named_by = true`, also the report and release passages that name a regulation (`published_market.mention`), newest first, as passage `ref`s with their citations and dates. A mention means "names": the passage's words say whether it announced, explained or merely cited the regulation. A release announcing a regulation is not the regulation.

**As built (2026-11-04):**
- **Every provider that links is asked,** and the gateway merges their links in turn, the owner of the ref first. `named_by` isn't an input: `names` is one of the `types`.
- **The regulation provider serves the contract's types,** copied into its index at each build, so they carry the index's version.
- **Order:** what changes the text comes first, so "is this still the rule?" is answered on the first page.
- **A document's links** are those with other documents. **A provision's links** also hold the references inside its document, and what changes the article or the document holding it.
- **The status history is on the document, not here:** `read` on a document's `ref` gives its `status_history`. It covers a revocation no link explains. A document's history stays short, where a page of links is shared with everything else.
- **`effective_on`** is the date the document stating the link took effect, since `published.edge` holds no date of its own. **`confidence`** is 0.9 where a source states the link, 0.6 where it was found by pattern in the text.
- **Each result gives refs, not citations.** The refs read plainly (`doc:ojk:pojk:2024:40`), and `read` cites them.

### `find_provision` (added in the build)

**Input:** `citation`, e.g. `POJK 40/2024 Pasal 137 ayat (3)`, `Fatwa 117`, `UU 27/2022 Pasal 5`.

**Output:** a page with one result, with its `ref`, wording and envelope.
- A citation naming a provision gives that provision.
- A citation naming only a document gives the document's card.

A citation whose document is published but whose provision is not gives `unknown_ref`, naming what is missing. The tool is exact: it doesn't depend on similarity.

**Why it exists:** when a question names its regulation, a search can still rank the right article below others. Served by the regulation provider, as its own tool.

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

**As built:**
- **Transports:** MCP at `/mcp` (streamable HTTP, stateless); the same catalog over plain HTTP.
- **Size limit:** an answer over 100,000 bytes is refused, saying how to ask for less.
- **Authentication is not built in the gateway.**
  - The production service, `retrieval-gateway`, is reachable only inside the VPC. It has no load balancer or service-discovery name yet, so an agent has no stable address for it.
  - The development service is public behind CloudFront, which checks a bearer token. It is for development only.
- **The call log** is written as daily JSON Lines files and as OpenTelemetry spans (`execute_tool {tool}`).
  - The spans are parented to the agent's trace, sent in MCP `_meta.traceparent` or the HTTP `traceparent` header.
  - The answering agent (mira-ai-chatbot) sends its Langfuse trace this way.
- **On AWS, neither is kept yet:**
  - no OpenTelemetry exporter is configured, so the spans are dropped;
  - the files are on the task's own disk, which is lost when the task is replaced.
  
  Langfuse accepts OpenTelemetry, so exporting there needs configuration, not code.

## Shape of the repository

As the connectors and the platform: Clean Architecture, with an architecture test that keeps dependencies pointing inward.
- `domain/`: evidence types, `ref`s, legal force, citations, fusion of rankings;
- `application/`: one use case per tool; ports for the read contracts, the index, the embedder;
- `adapters/`:
  - PostgreSQL (the read contracts, and the `retrieval` schema);
  - the embedding model;
  - the indexer, which follows `published.change_log` and the market schema's `published_at`;
  - MCP and HTTP.

**As built:** a uv workspace of five packages:
- `metamorph-retrieval-contract`;
- `metamorph-market-retrieval`;
- `metamorph-regulation-retrieval` (the provider and its index builder);
- `metamorph-retrieval-gateway`;
- `metamorph-retrieval-eval`.

Each package keeps its own rings, enforced by an architecture test ([retrieval-architecture.md](retrieval-architecture.md) §9).

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

**As built** ([eval/README.md](../../Metamorph-Retrieval/eval/README.md)):
- **The question sets:**
  - the **market set** has 54 cases over the seven tools;
  - the **regulation set** has 42 cases: mira-ai-chatbot's golden questions, each naming the retrieval units its answer needs (54 in all);
  - the **federated set** has 27 cases across both layers: 25 of 27 on AWS, with all 13 link cases passing.
- **Results on AWS, 2026-11-03,** through the gateway with reranking:
  - market: 52 of 54;
  - regulation: 14 of 42, against 3 of 42 for mira-ai-chatbot's own full-text client.
  - A search takes 3.6 s at p95.
- **How the regulation result was reached:**
  - **Searching units only, by words and meaning:** 6 → 12 of 42 for the provider alone.
  - **Mixing in market passages:** through the gateway, they took some of the first 8 places, and fused results fell to 9.
  - **The reranker** brought them back up and beyond, ranking both providers' candidates on one scale.
  - **Fifty rerank candidates instead of 25** give 16 of 42 at 6.9 s p95.

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

**As built:**
- **Filters take the built names: `documents` for `document_ids`, `kinds` for `kind`.
- **Every step runs today.**

## What the platform must add

| Piece | Why | Where |
|---|---|---|
| Reports and their passages: `published_market.report`, `report_passage` | Reports in `search_documents` and `read` | **Done** (Phase 4, live 2026-10-28: 13 reports, 1,943 passages; [market-data-layer-plan.md](market-data-layer-plan.md)) |
| `published_market.industry`: each curated industry with its registers, regulations, reports and datasets | `industry_context` | **Done** (Phase 4, Step 6, migration 0020) |
| `published_market.sector`: one curated industry across the sources' names, with what its industries link | `industry_context`'s starting point | **Done** (migration 0022, [market-curation-plan.md](market-curation-plan.md)); curators define the sectors |
| `reports[]` on `published_market.register` and `dataset`; a report's `discusses[]` | Reports from the market side, and from a report to the regulations it discusses | `reports[]` **done** (migration 0020). `discusses[]` is curation's; mentions (below) give the regulations a passage names |
| Releases and their passages: `published_market.release`, `release_passage` | Releases in `search_documents` and `get_provision` | **Done** (Phase 5, migration 0021) |
| `published_market.mention`: the regulations and companies each report or release passage names | `follow_links` with `named_by`; `find_companies` with `announcements` | **Done** (Phase 5, migration 0021) |

## Open questions

1. **The embedding model and where it runs.** It must handle Indonesian legal text well, and Arabic for fatwas would be a bonus. It runs locally first and on AWS later (deferred). To choose by the evaluation set, between a hosted multilingual model and an open one. *Settled: `BAAI/bge-m3`, chosen over `multilingual-e5-base` by the market set (M4). It runs inside the gateway and index tasks on Fargate, baked into the image.*
2. **One list of industries across sources.** *Settled 2026-10-29:* `published_market.sector` is one curated industry (e.g. `sharia-banking`) gathering each source's names, with what they link ([market-curation-plan.md](market-curation-plan.md)). Curators define the sectors in the console; none exists yet.
3. **The `sharia` force of a fatwa** that no regulation adopts. Is it `sharia` or `guidance`? For the project owner, with legal advice.
4. **Report passage size,** from Phase 4's Step 0b, and whether reports need a heading-aware split later (a general option in `metamorph-pdf-text`).
5. **A read-only SQL tool over a few market views,** for analysts' questions the seven tools don't cover. It waits for a need: open-ended SQL is harder to test and to guard.
6. **Where the retrieval layer is hosted,** and how the agent authenticates. With the AWS deployment, deferred. *Hosting settled 2026-11-03: ECS Fargate in Jakarta, beside the platform's RDS ([aws-deployment-plan.md](aws-deployment-plan.md)). Still open: a stable internal address for the production gateway, and how an agent authenticates to it.*
7. **The reranker's licence.** The deployed cross-encoder is Apache-2.0, but it was trained on mMARCO, which carries MS MARCO's research-only terms. For the project owner, before commercial use. `BAAI/bge-reranker-v2-m3` matched it on the regulation set.
