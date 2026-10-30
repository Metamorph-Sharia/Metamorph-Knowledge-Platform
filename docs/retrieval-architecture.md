# Retrieval architecture: providers, a shared contract, and a gateway

**Status: M0 to M4 built, 2026-10-30.** All five live in the new `Metamorph-Retrieval` repository:
- M0: the contract package, `metamorph-retrieval-contract` 0.1, reviewed and agreed by Friend 1;
- M1: the market evaluation set and its runner;
- M2: the market provider's exact tools over SQL;
- M3: the gateway (MCP and HTTP) and the regulation stand-in. Friend 1 can connect an agent now ([connecting-an-agent.md](../../Metamorph-Retrieval/docs/connecting-an-agent.md));
- M4: search over report and release passages, full text and bge-m3 embeddings fused, behind a gated index refresh.

M5 waits for Friend 2's provider. M6 is optional, and comes only if the evaluation set shows a gain.

**For:** the three of us.
- Market retrieval (this page's first build).
- LLM and agent evaluation (Friend 1).
- Regulatory RAG (Friend 2).

**What it does:** it turns [retrieval-tools-design.md](retrieval-tools-design.md) into an architecture that three people can build apart. That draft keeps its tools, principles, legal force and evaluation. What changes is who owns each part, and how the parts meet.

## Summary

- **The retrieval layer is split into providers.**
  - The **market provider** is ours, built now. It serves registers, companies, statistics, reports and releases.
  - The **regulatory provider** is Friend 2's. It serves regulations and fatwas.
  - Each provider owns its index, its chunking choices and its embedding model.
- **One small contract fixes what crosses the boundary:** `metamorph-retrieval-contract`.
  - **Refs:** which provider owns which namespace.
  - **The evidence envelope:** citation, legal force, dates and qualifiers.
  - **The provider protocol:** `manifest`, `search`, `read`, `describe`, `links` and the provider's own tools.
  - **Errors, versioning and a conformance suite.**
  
  If both providers pass the suite, they integrate without refactoring.
- **A thin gateway composes the providers for the agent.**
  - It routes by ref and fans a search out to the providers that hold the requested kinds.
  - It fuses their rankings and enforces budgets.
  - It serves everything over MCP and HTTP.
  - It has no knowledge of markets or regulations.
- **Retrieval is deterministic. Every generative step lives in the agent:** rewriting, condensing, grading, routing, web search and answering. This is what keeps retrieval independent of the agentic strategy. ReAct, CRAG, Self-RAG, plan-and-execute and supervisor graphs all reduce to calling the same tools and judging what comes back. The retrieval layer returns the signals they judge by.

## 1. The layers and who owns them

```
                    ┌──────────────────────────────────────────────────────────────┐
 Orchestration      │ Answering agent (Friend 1 evaluates models; strategy open)   │
 (generative)       │ condense · route · rewrite · grade · web/news · answer       │
                    └───────────────▲───────────────────────────┬──────────────────┘
                                    │ MCP tools (or HTTP)       │ trace context
                    ┌───────────────┴───────────────────────────▼──────────────────┐
 Retrieval gateway  │ routes refs · fans out searches · fuses (RRF) · budgets ·    │
 (deterministic)    │ partial results · tool catalog from provider manifests       │
                    └──────▲──────────────────────────────────────▲────────────────┘
                           │ metamorph-retrieval-contract         │
          ┌────────────────┴───────────────┐      ┌───────────────┴────────────────┐
 Providers│ Market provider (ours)         │      │ Regulatory provider (Friend 2) │
          │ report:, release:, dataset:,   │      │ doc: (regulations, fatwas)     │
          │ series:, company:, register:,  │      │ own index, chunking, model     │
          │ industry:, sector:             │      │ (adapter if not native)        │
          │ index: retrieval_market schema │      │                                │
          └────────────────▲───────────────┘      └───────────────▲────────────────┘
                           │ read only                            │ read only
 System of record  ────────┴── published_market ──────────────────┴── published ──────
 (built)            Platform: connectors → load → curate → publish (Airflow)
```

| Layer | Owner | May depend on | Must not know about |
|---|---|---|---|
| Orchestration | Friend 1, Friend 2 | the gateway's tool catalog, or its client | indexes, SQL, embedding models, which provider answers |
| Gateway | us | the contract only. Providers are plugged in at wiring | markets, regulations, agent frameworks |
| Market provider | us | the contract, and `published_market` (read only) | the agent, the gateway, the regulatory index |
| Regulatory provider | Friend 2 | the contract, and `published` (read only) | the agent, the gateway, the market index |
| System of record | us (built) | — | any of the above |

**The dependency rule across teams:** every arrow points toward the contract or the read contracts. An agent framework (LangGraph, Haystack, LangChain) appears only in orchestration, or in optional thin adapters (§9). It never appears in a provider or the gateway. So changing the agent never changes retrieval, and changing a provider's index never changes the agent.

## 2. The rule that keeps the agent free: no generative step in retrieval

Each agentic RAG pattern is a different loop around the same primitives. So the primitives stay in retrieval, and the loop and every model call in it stay in orchestration.

| Step | Where it lives | Why |
|---|---|---|
| Condensing a follow-up into a standalone query | Orchestration | It needs the conversation. Retrieval keeps no session |
| Rewriting, HyDE, multi-query, decomposition | Orchestration | Strategy-specific. Different agents will differ |
| Routing: which tools, kinds or providers | Orchestration, helped by `manifest()` | The agent's plan |
| Grading relevance, checking support, reflecting | Orchestration | Uses the signals retrieval returns (§5) |
| Web and news search | Orchestration | The platform never stores news ([market-data-layer-plan.md](market-data-layer-plan.md)) |
| Writing the answer and its citations | Orchestration | |
| Query embedding, hybrid search, filters, fusion | Retrieval | Deterministic. Same call, same result |
| Cross-encoder reranking | Retrieval, optional | A deterministic model. Kept only if the evaluation set shows a gain |
| Contextual headers for passages | Retrieval, at index time, optional | Generated offline, stored and versioned. Query time stays deterministic (§6.3) |

This keeps principle 4 of the tools design ("deterministic") and gives it a reason: it decouples the agent's strategy from retrieval.

## 3. The retrieval contract: `metamorph-retrieval-contract`

This is the one thing both RAG implementations must agree on. It is shaped like the existing contract packages (`metamorph-contract`, `metamorph-market-contract`):
- a small Python package with a JSON Schema for every wire shape;
- a `RETRIEVAL_CONTRACT.md`;
- tests that check the schemas against the types.

Its dependencies are the standard library, `jsonschema` and `pytest`, the last for its conformance suite.

### 3.1 Refs and namespace ownership

A ref is `{namespace}:{id}[#{address}]`, as the tools design already writes them. **Each namespace has exactly one owning provider**, and the gateway routes by it.

| Namespace | Owner | Example |
|---|---|---|
| `doc` | regulatory | `doc:ojk:pojk:2024:40#pasal-5/ayat-1` (the address is the `published.provision_unit` address) |
| `report` | market | `report:ojk:lpksi:2025#p-12` |
| `release` | market | `release:ojk:siaran-pers:2026:ojk-cabut-izin-usaha-pt-porto-ventura-kapital#p-1` |
| `dataset`, `series` | market | `series:bi:seki:tabel1_1:monthly:row=1` |
| `company`, `register` | market | `company:ojk:lpbbti:kep-49-d.05-2017`, `register:ojk:lpbbti` |
| `industry`, `sector` | market | `sector:sharia-banking` |

- **Ids come from the read contracts, never from an index.** A ref survives a re-index, a new embedding model or a new provider version. So refs can be cached, logged, put in evaluation sets and cited.
- **A provider may name refs it doesn't own.**
  - A market dataset's `governed_by` names `doc:` refs.
  - A release passage's mentions name `doc:` and `company:` refs.
  
  It names them and never resolves them. The gateway asks the owner (§4).

### 3.2 The evidence envelope

Every result, from any provider, has the same outer shape. Its body varies by kind.

```python
class LegalForce(StrEnum):
    BINDING = "binding"; SHARIA = "sharia"; EXPLANATORY = "explanatory"; NONE = "none"

@dataclass(frozen=True)
class Qualifiers:                    # what limits how much the evidence counts
    status: str | None = None        # documents: in_force, revoked, …
    valid_from: date | None = None
    valid_to: date | None = None
    under_review: bool = False       # a numbering gap the parser noted
    provisional: bool = False        # statistics: the source marks the period so
    as_of: date | None = None        # when the source last stood behind it

@dataclass(frozen=True)
class Provenance:
    provider: str                    # "market", "regulation"
    index_version: str               # which build of that provider's index answered
    source_published_at: datetime    # the read contract's publish this came from

@dataclass(frozen=True)
class Evidence:
    ref: Ref
    kind: str                        # regulation, fatwa, report, release, dataset, series, company, …
    citation: str                    # quote it as is
    title: str
    legal_force: LegalForce          # market evidence is always NONE
    qualifiers: Qualifiers
    published_on: date | None
    url: str | None
    body: Text | Figures | Record | None   # None in a describe() card
    provenance: Provenance
```

- **`Text`** holds `wording` and `pages`, capped. `read` returns the uncapped text.
- **`Figures`** holds observations with their periods, units and provisional marks.
- **`Record`** holds a company's or a dataset's fields.

These three bodies are all the agent ever parses.

### 3.3 The provider protocol

```python
class RetrievalProvider(Protocol):
    def manifest(self) -> Manifest: ...
    def search(self, request: SearchRequest) -> Page[Hit]: ...           # over the kinds it holds
    def read(self, ref: Ref, *, window: int = 0) -> Evidence: ...        # full body; window = neighbours
    def describe(self, refs: Sequence[Ref]) -> Sequence[Evidence]: ...   # cards, batched, cheap
    def links(self, ref: Ref, request: LinksRequest) -> Page[Link]: ...  # what it knows about a ref, owned or not
    def call(self, tool: str, arguments: Mapping[str, object]) -> ToolResult: ...  # its own tools
```

- **`Manifest`** holds:
  - the provider's name and version, and the contract version;
  - the namespaces it owns and the kinds it can search;
  - its optional capabilities (`links`, `call`);
  - its own tools as `ToolSpec`s: name, description, input and output JSON Schemas, and version;
  - `index_version` and `data_as_of`.
  
  The gateway builds the agent's tool catalog from manifests. So a new provider, or a new market tool, needs no gateway code (open for extension, closed for modification).
- **`describe` leaves out the refs it doesn't hold, and raises no error for them.** A link may name a regulation that isn't published yet: 613 of the 720 regulations named in reports and releases are published.
- **`SearchRequest`** carries the filters every text search shares:
  - `query`;
  - `kinds[]`, `issuers[]`, `document_ids[]`;
  - `published_from`, `published_to`, `in_force_on`, `legal_force[]`;
  - `sort` (`relevance` or `newest`);
  - `limit` (at most 25) and `cursor`.
  
  A provider ignores a filter it cannot apply to its kinds and says so in `warnings`.
- **`Hit`** is an `Evidence` plus `rank`, `score` and `matched_by` (`semantic`, `words`, or both). A `score` is comparable only within one provider and one call. That is why the gateway fuses by rank.
- **`Page`** holds `items`, `cursor`, `empty_reason` and `warnings`.
  - `empty_reason` is `no_match` or `filters_exclude_all`.
  - "Nothing found" is an empty page with a reason, never an error.

### 3.4 Errors and versioning

- **Typed errors:** `unknown_ref`, `unknown_tool`, `invalid_argument`, `capability_missing`, `provider_unavailable`. Each comes with a message the agent can act on.
  - A limit over 25 is an `invalid_argument` that states the maximum. The schema's `maximum: 25` already shows agents the cap, so a separate `limit_exceeded` would only mean two codes for one mistake.
- **Semantic versioning.** A breaking change to a wire shape or a tool's schema is a new major version, served beside the old one until every caller has moved. Tool descriptions and schemas stay byte-stable within a version. This also keeps the agent's prompt cache warm (§7.2).

### 3.5 The conformance suite

A function in the contract package, `conformance_problems(provider, samples)`, run against any provider. It returns every problem found, so any test framework can assert that the list is empty. It checks:
- every ref a provider returns parses, and is in a namespace it owns or one it names;
- `read(ref)` and `describe([ref])` agree on the card;
- unknown refs raise `unknown_ref`;
- empty pages carry a reason;
- limits are enforced;
- the same call gives the same result within one `index_version`;
- every tool's output validates against its schema.

A provider's own rules, such as the market's `legal_force: none`, belong in that provider's tests.

Friend 2's provider passes the same suite, natively or through an adapter (§10).

## 4. The gateway

The gateway composes providers and adds no domain knowledge.

- **Routing.** `read`, `describe` and provider tools go to the owner of the ref's namespace, or of the tool.
- **Federated search.** `search_documents` fans out to the providers whose manifests hold the requested kinds, in parallel and each with a timeout. It fuses their pages with reciprocal rank fusion (k = 60, ties broken by ref). A fused page's cursor encodes each provider's own cursor.
  - **Built in M5, not M3.** Fusion only matters once two providers search, which is when Friend 2's joins. Until then the gateway sends a search to the one provider holding the kinds asked, and links to the one provider answering links. Building fusion against fakes now would fix a cursor design no real second provider has tested.
- **Federated links.** `follow_links` asks every provider that declares `links`, and merges what they return.
  - The regulatory provider answers amends, revokes and implements.
  - The market provider answers `named_by`: which report and release passages name a `doc:` ref, from `published_market.mention`.
  
  Neither provider knows about the other.
- **Enrichment.** When a market result names `doc:` refs, such as a dataset's `governed_by`, the gateway can add their citations and status with one batched `describe` to the owner. The market provider never reads `published`.
  - **As built:** each `{"ref"}` stub in a record's fields that **another** provider owns gets its owner's `kind`, `citation`, `title`, `legal_force` and `status`. What the stub already says is kept. A provider's own refs are left as it named them, since it could have cited them itself. Citing everything starved the regulations in the live run: 35 market refs used up the budget first.
  - At most 40 refs are cited per answer. Past that, or when an owner is late, the refs stay bare and the page's `warnings` say so.
- **Budgets and degradation.** The gateway caps result counts, field lengths and response size, with a timeout per provider. If one provider fails or is late, the others' results come back with `warnings: [{provider, reason}]`. A failure is reported; it never empties the page silently.
  - **As built:** each provider call has 10 seconds (`METAMORPH_RETRIEVAL_TIMEOUT`). A late or crashing provider is `provider_unavailable`, naming it but not its internals. Its own errors pass through.
  - An answer over 100,000 bytes is refused as `invalid_argument`, saying how to ask for less. Field lengths stay the providers' own: the platform's passages are already bounded.
  - A late provider's query isn't killed, only no longer awaited. So each provider's session has an 8-second statement timeout, under the gateway's budget.
- **Interfaces.**
  - MCP is primary: one tool per contract operation and per provider tool, each with its schema and description.
  - HTTP and OpenAPI serve tests and non-MCP clients.
  - A small Python client serves orchestration code.

```python
class FederatedSearch:
    def run(self, request: SearchRequest) -> Page[Hit]:
        targets = self.providers.holding(request.kinds)
        answers = self.fan_out(targets, lambda p: p.search(request.for_provider(p)), timeout=self.timeout)
        fused = reciprocal_rank_fusion([a.page.items for a in answers.ok], k=60)
        return Page(items=fused[: request.limit], cursor=answers.next_cursor(),
                    empty_reason=None if fused else answers.empty_reason(),
                    warnings=answers.failures())
```

## 5. The agent-facing tools

These are the seven tools from the tools design, with an owner each and one rename.

| Tool (MCP) | Served by | Notes |
|---|---|---|
| `search_documents` | gateway: federated `search` | Regulations and fatwas from the regulatory provider; reports and releases from the market provider |
| `read` (was `get_provision`) | gateway → owner | Renamed because it reads any ref: an article, a report passage with `window`, a company, a dataset |
| `follow_links` | gateway: federated `links` | Edges from the regulatory provider; `named_by` mentions from the market provider |
| `find_series` | market provider tool | Two stages (§6.2) |
| `get_observations` | market provider tool | SQL only. Values are never embedded |
| `find_companies` | market provider tool | Adds `as_of` (§6.4) |
| `industry_context` | market provider tool | Starts from `sector`, then `industry`. Returns `doc:` refs the agent passes to `search_documents(document_ids=…)` |

**Signals every result carries, whatever the strategy:**
- `score`, `rank` and `matched_by`, for a relevance grader;
- `empty_reason`, so the agent can tell "rephrase" from "widen the filters";
- explicit filters, so widening is the agent's own decision and never hidden;
- refs, so any hop can feed the next;
- `legal_force` and the qualifiers, so evidence can be weighed;
- `provenance.index_version`, so an answer can be traced to the index that served it.

### How agentic strategies use the same tools

| Strategy | What it needs from retrieval | Where it gets it |
|---|---|---|
| Static RAG (one retrieve, then answer) | a retriever | `search_documents` |
| ReAct or tool calling | typed tools with good descriptions | the MCP catalog built from manifests |
| Adaptive RAG (route first) | what kinds and sources exist | `manifest()`; one toolset per provider |
| Corrective RAG (CRAG) | a relevance signal, and a way to widen or fall back | `score` and `matched_by`; `empty_reason`; explicit filters. Web fallback is the agent's |
| Self-RAG | full text to check an answer's support against | `read(ref, window=n)` |
| Multi-hop | stable handles to chain | refs: `industry_context` → `search_documents(document_ids)` → `follow_links` |
| Plan-and-execute | replayable steps | determinism within an `index_version` |
| Conversational RAG | stateless calls on standalone queries | condensing is the agent's; retrieval holds no session |
| Supervisor and sub-agents | toolsets that split cleanly | one toolset per provider: a market analyst and a legal specialist |

## 6. The market provider

### 6.1 Rings (Clean Architecture, as in the platform)

```
metamorph_market_retrieval/
  domain/       refs for its namespaces; evidence building per kind; periods (2026-08, 2026-Q2, 2025);
                company-name normalisation for lookup; reciprocal rank fusion; citation shapes
  application/  one use case per operation: SearchPassages, Read, Describe, Links (named_by),
                FindSeries, GetObservations, FindCompanies, IndustryContext; BuildIndex, ActivateIndex
                ports: MarketReadModel (published_market), PassageIndex, DatasetIndex, Embedder,
                       IndexVersions, CallLog, Clock
  adapters/     postgres/ (published_market reader; retrieval_market index: pgvector + full text)
                embedder/ (local model first; hosted later, behind the same port)
                provider.py (implements the contract's RetrievalProvider over the use cases)
  wiring.py
```

An architecture test, like the platform's, keeps domain ← application ← adapters. The contract package is the only outside import the domain is allowed.

### 6.2 What is indexed, and how each kind is found

Chunking is the platform's job, and it is done. Report passages are 250–400 words with pages; release passages are at most 400 words. Retrieval **never re-chunks**, because citations and refs depend on the platform's addresses. Retrieval builds only the *text it indexes* for each unit.

| Record | Index unit | Found by | Embedded |
|---|---|---|---|
| Report passage (~1,900) | the platform's passage | hybrid: full text plus vectors, fused | yes: `"{report citation}, hlm. {pages}\n{text}"` |
| Release passage (~3,700) | the platform's passage | hybrid | yes: `"{citation}: {title}\n{text}"`. The header names the company or regulation that a later passage often doesn't |
| Dataset (~1,400, ~1,950 when BPS is complete) | a dataset card: metric, group, industry, source, dimension names, frequency, period span | hybrid | yes |
| Series (~240,000, mostly BPS regions) | its label, within its dataset | full text and trigram on labels, inside the chosen datasets | no, at first: the dataset card carries the meaning, and labels differ mostly by region or account |
| Observation (~3.7 million) | none | SQL by series and period | never |
| Company and entity (166 and 243) | legal and other names | normalised exact match, then trigram | no |
| Sector and industry (tens) | id, names, the industries' names | full text and trigram | no, unless the evaluation set asks for it |

**As built (M4):**
- **Indexed:** passages, dataset cards, and industry and sector cards. The question set asked for the last two: its English industry questions failed on words alone.
- **Full text** uses PostgreSQL's `indonesian` configuration, whose stemmer joins *pembiayaan* and *dibiayai*.
  - A match by words must hold **at least half of the question's stems**. Joining them by OR alone matched every question on some common word, so no question ever got `no_match`.
- **Embeddings:** `BAAI/bge-m3`, run locally.
  - It was chosen over `multilingual-e5-base` by the question set. e5's similarities crowd into 0.74–0.91, off-topic and relevant alike, and it ranked worse.
  - A match by meaning below **0.45** is dropped, calibrated against off-topic questions.
- **Search is exact,** without HNSW: 7,022 units, at p95 174 ms through the gateway.
- **Fusion** is reciprocal rank fusion of the two rankings. Ties go to the words' order, which keeps M2's rule that a table's successor comes before it.
- `find_series` stage 1 and `industry_context` fuse the cards' meaning the same way ([eval/market/runs/2026-10-30-m4-models.md](../../Metamorph-Retrieval/eval/market/runs/2026-10-30-m4-models.md)).

**`find_series` is retrieval in two stages** (hierarchical indexing):
1. Rank the datasets for the query.
2. Find the series inside the top datasets by label, with dimension filters.

Results come grouped by dataset. Embedding 240,000 near-identical labels would cost more and rank worse.

**Small-to-big through tools.** `search_documents` returns one passage. `read(ref, window=1)` returns that passage with its neighbours and its report's card. The agent widens the context only when it needs to: the parent-document pattern, as a tool.

### 6.3 Contextual headers (optional, measured)

- **The deterministic headers above come first.** They cost nothing and repair most passages that lack context.
- **Model-written context** (Anthropic's contextual retrieval: a model writes a line situating each passage in its document) is an index-time option:
  - written by a small model with the document prompt-cached;
  - stored per passage and keyed by a content hash;
  - versioned with the index.

  It is adopted only if the evaluation set shows a recall gain over the deterministic headers. About 5,600 passages sits at the low edge of where the technique pays.

### 6.4 Time

Market questions are mostly about time, so time is explicit everywhere and never hidden in the ranking.
- **Filters:**
  - `published_from` and `published_to` for reports and releases;
  - periods for observations;
  - `sort: newest` when the agent wants the latest.
  
  There is no hidden recency decay. If the evaluation set shows the agent needs one, it becomes an explicit parameter.
- **A company's standing on a date.** `find_companies(as_of=2023-06-30)` answers from the register edition current that day, through `published_market.edition` and `listing`. That is "who was licensed then", not only "who is licensed now".
- **Statistics are as the source gives them now.** A revised figure replaces the old one, and there are no vintages. `as_of` is the dataset's `updated`, and `provisional` marks what the source marks.
- **Freshness.** Every response's provenance carries `source_published_at`. An index whose source has been republished since it was built is reported in health, and alerted on.

### 6.5 Finding companies by name, without merging them

- **Retrieval looks companies up; it never merges them.**
  - A name is normalised: case, spacing, punctuation, and `PT`, `Tbk` and `(Persero)` dropped.
  - It is matched exactly, then by trigram.
  - Each candidate comes back with its `match` (`exact`, `normalised` or `fuzzy`) and its score.
- **An ambiguous name returns several candidates.** The agent decides, or asks the user.
- **Joining records into one company is the platform's**, as the system of record. It already joins a register's records by legal name. Matching across registers, if it is ever needed, belongs to the platform's curation, not to an index.

### 6.6 Building the index

```
market_publish (built) ──outlet metamorph://published-market──► market_index (new DAG)
   BuildIndex: read published_market → index units → hash(text, model) → embed only new hashes
             → write retrieval_market at a new index_version
   Gate: evaluation set on the new version ≥ the active version (§8)
   ActivateIndex: one row flips the active version; the previous one is kept for rollback
──outlet metamorph://market-index──►
```

- **The embedding cache makes rebuilding cheap.** Its key is `sha256(text)` with the model. A market publish rebuilds the whole schema, but unchanged passages re-embed nothing.
- **Versions are blue-green**, and the query path never waits on the index path. A new embedding model or header scheme is a new `index_version`, built beside the active one.
- **The index stays inside the platform's Airflow graph.** `market_index` follows `market_publish` through an Airflow Dataset, like the rest of the graph. It stays paused like the other DAGs until the project owner unpauses them.
- **As built (M4):**
  - `metamorph-market-index` runs `prepare`, `build`, `versions` and `activate`. A build writes only `retrieval_market`: `index_version`, `unit` and `embedding_cache`.
  - `scripts/refresh-market-index.sh` builds a version, runs the question set on the active one and on it, and activates it only if `metamorph-eval compare` finds it no worse. It exits 3, failing the DAG task, when the new version is worse.
  - The `market_index` DAG (paused) runs that script in the `metamorph/retrieval` image after each `market_publish`. Models are kept in the `metamorph-models` volume.
  - A rebuild of unchanged text embeds nothing: 7,022 units in 15 s from the cache.

## 7. Cross-cutting concerns

### 7.1 Observability

- **Tracing.** The gateway and the providers emit OpenTelemetry spans: `tool` → `provider.search` → `lexical`, `vector` and `fuse`.
  - Each span carries the tool, provider, `index_version`, `limit`, result count, top score, `empty_reason` and latency.
  - Trace context comes in from the agent: MCP request `_meta` or the HTTP `traceparent` header. One question is then one trace across the agent and retrieval.
- **Call log.** `retrieval.call_log` keeps each call's tool, arguments, returned refs, scores, `index_version`, `trace_id` and latency, with a retention period.
  - **As built (M3):** daily JSON Lines files (`var/call-log/calls-YYYY-MM-DD.jsonl`, kept 30 days), not a table. The gateway's database sessions are read only, and a table of its own would need a writing role and a platform migration. The lines are that table's rows, so moving to it later is a `COPY`.
  - Spans are named `execute_tool {tool}` (the GenAI conventions). Over MCP, they nest under the MCP server's own span, which reads the agent's `_meta.traceparent`.
  - It is how a bad answer is debugged: was the expected ref in the index, retrieved, or ranked too low?
  - It is also where new evaluation questions come from.
- **Alerts:**
  - the rate of empty results;
  - p95 latency per tool;
  - provider errors and timeouts;
  - index lag behind `published_market`.

### 7.2 Caching

| Layer | Key | Lifetime | Where |
|---|---|---|---|
| Passage embeddings | `sha256(text)` and the model | permanent | `retrieval_market.embedding_cache` |
| Query embeddings | query and model | in-process LRU | provider |
| Tool results | tool, canonical arguments, `index_version` | until the version changes | gateway, added only when latency needs it |
| The agent's prompt | stable tool catalog first | provider-managed | orchestration. Byte-stable tool schemas keep it warm |
| Answers | — | — | never in retrieval. Generation is the agent's, and so is any answer cache |

Determinism is what makes the result cache safe: a new `index_version` invalidates every result cached under the old one.

### 7.3 Scale and operations

- **Stateless services.** The gateway and the providers scale horizontally. A provider can run in-process in the gateway (one deployable, now) or behind HTTP (its own deployable, later). Only the contract's transport adapter changes, never the code on either side of it.
- **One PostgreSQL holds today's volume comfortably.**
  - The vectors are about 7,500 passages and 2,000 dataset cards, with pgvector HNSW.
  - Observations are SQL with indexes.
  - A read replica comes first if queries contend with publishing. Partitioning is not needed at these sizes.
- **Full text in Indonesian.** PostgreSQL's `indonesian` text search configuration is checked in step M3 (`\dF indonesian`), with the `simple` configuration for ids and numbers. *Used from M4 for the index's full text.*
- **AWS waits for the project owner**, as everywhere else.

## 8. Evaluation

Retrieval is judged on its own, apart from answers, so that "retrieval missed it" and "the model misread it" can be told apart when different people own each half.
- **A market evaluation set, written before the search code.** Forty to sixty questions across the customer journey, each naming the refs, series or companies it should find (as in the tools design's table).
- **Measures:**
  - for the searches: recall in the first 8 results, and the reciprocal rank of the first expected result;
  - for the exact tools: an exact match with the expected records;
  - p95 latency for each.
- **Gates:**
  - an index version is activated only if its evaluation results are no worse than the active version's;
  - a ranking change merges only with the same result.
  
  As in [engineering-principles.md](engineering-principles.md), only these few gates block. Everything else is monitored.
- **A federated set**, once Friend 2's provider is in: cross-layer questions ("which regulations govern sharia P2P lending, who is licensed under them, and what did OJK announce?").
- **For Friend 1:** a stable tool catalog means models and agent strategies can be compared on the same retrieval, and retrieval can be improved without moving their baseline.

## 9. Repository layout

A new repository, **`Metamorph-Retrieval`**: a uv workspace like the platform's, with its own releases and deploys. Friends contribute here without touching ingestion.

```
Metamorph-Retrieval/
  packages/
    metamorph-retrieval-contract/   refs, evidence, provider protocol, errors, JSON Schemas,
                                    RETRIEVAL_CONTRACT.md, conformance suite (pytest plugin)
    metamorph-market-retrieval/     the market provider (§6)
    metamorph-retrieval-gateway/    routing, budgets, enrichment, the catalog; adapters: MCP, HTTP, call log, spans;
                                    client.py; wiring.py names the providers (module:function), never imports them
    metamorph-regulation-standin/   read and describe over published.* only, until Friend 2's provider arrives
  integrations/                     optional, orchestration side: thin LangGraph and Haystack wrappers
  eval/                             question sets (JSONL), runner, reports
  tests/test_architecture.py        the dependency rules below
```

**Dependency rules, enforced by the architecture test:**
- the contract imports nothing from this repository;
- providers import only the contract;
- the gateway's domain and application import only the contract. Providers are joined in `wiring.py`;
- `integrations/` imports only the gateway client;
- only `integrations/` may import LangChain, LangGraph or Haystack.

An `integrations/` wrapper is a few lines. The orchestrator's graph stays Friend 1's:

```python
client = RetrievalClient.mcp(url)                   # or .http(url), or in-process for tests
tools = client.langchain_tools()                    # from the manifests' schemas
agent = create_react_agent(model, tools)            # or a CRAG graph whose retrieve node calls client.search(...)
```

## 10. Meeting Friend 2's regulatory RAG

**Agree on these now, before either side builds more.** Each is cheap now and expensive to retrofit.
1. **Cite by the platform's addresses.** Whatever their chunking, each hit maps to a `published.provision_unit` address, as `doc:{document_id}#{address}`. Without this, citations from the two layers can't be unified, and the market's `governed_by` and mentions can't be joined to their results.
2. **Carry the envelope:** `legal_force` derived from `document.kind` (the tools design's table), with `status`, `valid_to` and `under_review`.
3. **Keep their retrieval deterministic, and separable from their generation.** We integrate their retrieval as a provider. Their answer loop is one of the orchestration strategies Friend 1 can compare.
4. **Implement `describe(refs)`, batched.** The gateway uses it to put citations on the `doc:` refs that market results name.
5. **Accept trace context**, so one question is one trace.

**When their repository arrives:**
- If it already speaks the contract, register it with the gateway.
- Otherwise, write an **adapter** in `metamorph-retrieval-gateway/adapters/providers/regulation/`. It maps their API onto `RetrievalProvider` and translates their ids into `doc:` refs. Their code is untouched.
- Then run the conformance suite on it, then the federated evaluation.
- The stand-in provider is retired.

**Until then, however long it takes**, the stand-in reads `published.document` and `provision_unit` for `read` and `describe` only. It never searches. Market results get their regulation citations end to end, and Friend 1 has a whole tool catalog to test against. The stand-in also keeps the contract honest: it exercises the `doc:` namespace and cross-provider `describe`, so the contract doesn't drift into a market-only shape while Friend 2 is away.

## 11. Plan

**Friend 1 first; Friend 2 when ready (decided 2026-10-30).** Friend 2's timeline is uncertain, so no step before M5 waits on it. The gateway comes before search, so Friend 1 can call real tools as early as possible.

| Step | Work | Done when |
|---|---|---|
| M0 ✓ (Friend 1 agreed, 2026-10-30) | `metamorph-retrieval-contract` 0.1: refs, envelope, protocol, errors, schemas, conformance suite. Friend 1 reviews §3 and §5. §10's list goes to Friend 2 as a request, and their answer blocks nothing | Friend 1 has agreed to §3 and §5; the suite runs against a fake provider |
| M1 ✓ | The market evaluation set and its runner. **Built 2026-10-30:** `Metamorph-Retrieval/eval/market/cases.jsonl` has 54 cases (12 macro, 27 industry, 1 product, 14 compliance) over all seven tools. Every expected ref (99) and figure was checked against the live data. `metamorph-retrieval-eval` (`metamorph-eval check` and `run`) reports per tool and per phase. The set fixes M2's output conventions ([eval/README.md](../../Metamorph-Retrieval/eval/README.md)) | 40–60 questions with expected refs; the runner reports per tool |
| M2 ✓ | Exact market tools over SQL: `find_companies` (with `as_of`), `industry_context`, `get_observations`, `read`, `describe`, `named_by` links, and `find_series` by lexical match. **Built 2026-10-30:** `metamorph-market-retrieval`, with domain, application and adapter rings enforced by a test, and one read-model test set run in memory and on PostgreSQL. **Live run:** all 30 exact cases pass; `find_series` passes 7 of 9 and `industry_context` 2 of 4 (the misses are English queries, and one ambiguous case); 32 of 54 cases overall, since search waits for M4 ([eval/market/runs/2026-10-30-m2.md](../../Metamorph-Retrieval/eval/market/runs/2026-10-30-m2.md)). Conformance passes on the live data. **The call log moved to M3:** the gateway sees every call, across providers | The evaluation's exact cases pass; conformance passes |
| M3 ✓ | **Friend 1 starts here.** The gateway: MCP and HTTP, budgets, tracing, the call log, the stand-in regulation provider. Tool catalog 0.x: the M2 tools. **Built 2026-10-30:** `metamorph-retrieval-gateway` and `metamorph-regulation-standin`, each with its rings enforced by a test.<br>**Live:**<br>• An MCP client over streamable HTTP called every M2 tool, 10 calls in about 0.5 s.<br>• The question set run end to end through the gateway's HTTP client gives 32 of 54, identical to M2 case by case.<br>• A live provider past its budget returned `provider_unavailable`: a 503 over HTTP, `isError` over MCP.<br>• Market answers' regulations now come back cited by the stand-in.<br>**Deviations:** fusion moved to M5; the call log is files ([eval/market/runs/2026-10-30-m3.md](../../Metamorph-Retrieval/eval/market/runs/2026-10-30-m3.md)) | Friend 1 calls every M2 tool end to end from their agent; a provider timeout returns a typed error |
| M4 ✓ | Search: full text first, then embeddings fused by RRF, for passages and dataset cards. `search_documents` joins the catalog, adding a tool without breaking any. `market_index` DAG, index versions, embedding cache. **Built 2026-10-30:** search, index versions and the cache in `retrieval_market`; `metamorph-eval compare` as the gate; the refresh script and the paused DAG.<br>**Live:** `market-2026-10-30.6` (bge-m3) was activated by the gate.<br>• All cases: 52 of 54, recall 0.89, MRR 0.82, up from 32 of 54.<br>• `search_documents`: 18 of 19, recall 0.74 against full text's 0.68.<br>• `industry_context` 4 of 4, `find_series` 8 of 9.<br>• Search p95 is 174 ms through the gateway ([eval/market/runs/2026-10-30-m4.md](../../Metamorph-Retrieval/eval/market/runs/2026-10-30-m4.md)).<br>**Beyond the plan:** industry and sector cards are indexed; the half-the-words rule; a similarity floor | Recall in the first 8 results beats the full-text baseline on the set; activation gated |
| M5 | **When Friend 2's provider is ready, however late:** register it natively or through an adapter; the gateway's search fusion (RRF) and link merging, moved here from M3; the federated evaluation set; the stand-in retires | Conformance passes; federated questions meet their expected refs |
| M6 | Only if the evaluation set shows a gain: a reranker, model-written context headers, a result cache | Each one's gain measured, or it isn't added |

**Until M5, Friend 1 should know:**
- `search_documents` finds reports and releases only.
- Regulations can be read and described by ref (through `industry_context`, `governed_by` and mentions), but not searched.
- So compliance questions (journey phases 3–4) can be evaluated only as far as following those refs.
- Catalog 0.x may still change: each change is announced, and 1.0 freezes before anyone depends on it in production.

The market provider is built tests-first, in small steps, with the clean-architecture and Kent Beck practices the platform uses.

## 12. Decisions for the project owner

1. **A new repository, `Metamorph-Retrieval`,** rather than more packages in the platform repository. Retrieval then gets its own release cadence and its own contributors. *Created 2026-10-30 with M0.*
2. **We own `metamorph-retrieval-contract`.** Friend 2 implements it, or we adapt to their API. Either way, it stays the one boundary.
3. **Rename `get_provision` to `read`.** It reads any ref, and the name should belong to neither layer.
4. **A stand-in regulation provider** (read and describe only) until Friend 2's arrives.
5. **The embedding model is chosen in M3 by the evaluation set.** It must handle Indonesian; this is open question 1 of the tools design. A local model comes first. A hosted one waits for AWS. *Chosen in M4: `BAAI/bge-m3`, over `multilingual-e5-base`.*

## Open questions

- **Friend 1's constraints:** how many tools, and which JSON Schema features, their candidate models handle well; and a token budget per result. They may change §3.4's caps and the descriptions' length.
- **Friend 2's chunking:** if their units are not the platform's `provision_unit`s, how each maps to an address (item 1 of §10).
- **A read-only SQL tool** over a few market views (open question 5 of the tools design). It is still waiting for a need the seven tools don't meet.
