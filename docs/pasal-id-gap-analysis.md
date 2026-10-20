# Pasal.id as a reference: what the curation console lacks, and the plan to close it

> **Status (2026-10-20): built.** Releases A–D are implemented (§8). The decisions are in §7. Release D is reduced to G12. It compares Pasal.id (studied on 2026-10-20) with Metamorph-Curation-Web and the curation API as they stand after the Phase 4 cut-over.

## 1. The question, and the lens

Pasal.id is a **public reader** of Indonesian law. It serves about 199,000 regulations and 3.97 million structured articles to anyone, for free. The curation console is an **internal tool** for a small team. Its job is to make sure what the assistant cites is right. So we don't copy Pasal.id; we borrow what helps a curator do these three things:

1. **Read** a regulation the way the parser read it, and tell whether the parser read it right.
2. **Find** documents, and the article inside them, quickly and across the whole corpus.
3. **Understand** where a regulation stands: what it changes, what changed it, and whether it is still in force.

Features that only make sense for the public, such as reading quotas, public accounts, a public API and MCP, or SEO FAQs, are listed in §5 and left out of the plan.

**How this was checked.** Pasal.id: its home page, a regulation page (UUD 1945, Fourth Amendment), an amended law (UU 13/2003), an article page (UU 8/1999 Pasal 60), search, browse by type, methodology, editorial policy, API and Hubungkan AI. Ours: the console's routes and components, the curation API's routes and read models (`application/views.py`, `adapters/postgres/views.py`), the database migrations, and the `published` contract (`docs/published-schema.md`). Docker wasn't running on 2026-10-20, so the screens and data volumes weren't checked live. The findings come from the code, which is what the screens render.

## 2. What Pasal.id offers

| Area | What it does |
|---|---|
| **Regulation page** | Breadcrumb (Home › type › regulation). Title with a status badge (Berlaku, Diubah, Dicabut) and a verification badge. For amended laws, "Naskah asli, bukan terkini". **Table of contents** (Daftar Isi) by BAB, then Pasal, collapsible ("+12 pasal lainnya"). **Every article rendered in full**, with its ayat, each with an anchor (`#pasal-11`). **Tampilkan PDF**: the original PDF inline beside the text. Disclaimer: not legal advice. |
| **Per-article actions** | **Tautan** (link to the article) and **Salin** (copy its text) on every article. Each article also has its own page (`…/pasal-60`) with previous and next article, a link back to the full text, and **references to other articles as hyperlinks** ("Pasal 19 ayat (2)"). |
| **Metadata panel** | Status details. Verification tier and "Terakhir diperiksa" (when last checked). Issuer. Place and date enacted. Date promulgated. LN/TLN numbers. Source (BPK / peraturan.go.id). Links: original PDF, source page. |
| **Relationships** | **Pohon peraturan** (regulation tree): **Mengubah** (amends), **Diubah oleh** (amended by, e.g. UU 13/2003 ← UU 11/2020, Perppu 2/2022, UU 6/2023), and revocations. Links to "other regulations" of the same type and year. |
| **Search** | One box. Results mix **whole regulations and single articles** (an article hit links to `…/pasal-60` with an excerpt). Filters: type, year, status, with counts per type. Paginated (10 per page). |
| **Browse** | By type (`/jelajahi/uu`), then by year chips (1945–2026) and status. Newest first. Counts per type. |
| **Trust and transparency** | Verification is shown as tiers, not as a single "verified" badge: human-reviewed; golden-verified (it reproduces a locked reference tree); automatically checked against the source; processed, not yet reviewed; limited evidence. A methodology page and an editorial policy. |
| **Corrections and requests** | "Ada masukan?" reports wrong content (`/masukan?type=konten_salah&page_url=…`), and there is a request to add a missing regulation. Per the editorial policy, corrections go to an admin review queue and are applied with an audit trail, or rejected with a reason. |
| **Machine access** | Discovery API (`/api/v1/search`, `/laws`, `/laws/{frbr_uri}`: metadata only, token, rate limits). MCP server with six tools: `search_legal`, `resolve_law`, `get_law_context`, `read_law`, `search_court_decisions`, `report_issue`. |
| **Public product** | One regulation a day without an account, unlimited when signed in. Save (Simpan). Indonesian and English UI. Court decisions (Putusan MK). |

## 3. What we already have

What our platform knows is as rich as what Pasal.id shows. The gaps are in what the console *shows*, not in what the platform *holds*.

### 3.1 In the platform (data and rules)

| Capability | Where it lives | Notes |
|---|---|---|
| Parsed structure, down to the ayat, Penjelasan and Lampiran | `domain/structure/` (grammars for Peraturan, Surat Edaran, Fatwa); `registry.provision`, `published.provision` | Addresses such as `pasal-5/ayat-1`, `penjelasan/pasal-5`, `pasal-i/pasal-115`. Every provision has `char_start`/`char_end` and pages. `published.provision.body` holds the text. `registry.provision` holds only offsets into the text. |
| Per-article amendment state | `provision.valid_to` | Set when a later instrument amends or revokes the article. |
| Relationships with legal meaning | `registry.link`: `legal_basis`, `implements`, `amends`, `supersedes`, `revokes`, `partly_revokes`, `adopts_fatwa`, `changes_fatwa`, `refers_to` | Article-level ends (`from_address`, `to_address`). Taken from the sources' lineage and from the text itself (Mengingat, closing provisions, amending instructions). |
| Status, and its history | `document.status` (six values); `status_event` (whole document or one article) | Where a source gives no status, it is derived from links. |
| Dates | enacted, promulgated, effective, status-as-of | Read from the closing text when a source gives none. |
| Several sources per document | `registry.document_source`, with `missing_since` | |
| Text versions | `registry.text_version`, `is_current` | Older versions are kept, never deleted. |
| Quality gate and curation | publish gate, approvals, text corrections, field overrides, suppression, conflicts, review queues | Every decision has an author, a reason and a time. |

### 3.2 In the console (screens)

| Screen | What a curator can do | Limitations, checked in the code |
|---|---|---|
| **Overview** `/` | Held and review counts, ingestion health, documents by issuer, latest bundles | Counts per issuer only. Nothing by family or year. |
| **Held** `/held?check=` | Held documents, filtered by check, paged | — |
| **Review** `/review?kind=` | Conflicts, unlinked citations and quarantined lines, each decided with a note | — |
| **Documents** `/documents?q=` | Search by ID, citation, title or alias | `ILIKE` on metadata only (`views.search`). **No search in the text or articles. No filters. No paging. Capped at 50 results** (`SEARCH_LIMIT`). No browsing without a query. |
| **A document** `/documents/{id}`: ten sections | **Fields:** effective, registry and per-source values, each correctable. **Sources:** with links and "gone since". **Files & Texts:** open in a new tab; approve as is; edit; withdraw. **Open citations:** link them. **Conflicts** and **Review items:** decide them. **Links:** two tables, "This document cites" and "Cited by". **Status history:** a table. **Structure:** an outline. **Manage:** assign an ID, suppress, restore. | See §4. In short: **Structure** shows labels and headings but no article text. It is capped at 400 provisions and shows the first main text only, with no anchors. **Links** show the raw relation types (`Amends`, `Partly revokes`) in two flat tables. **The text opens as a raw file.** Older text versions aren't shown (the query reads `is_current` only). |
| **Edit the text** `…/texts/{sha}/edit` | CodeMirror over the whole text: find and replace (from `basicSetup`), page markers protected | Opens at the top. You can't jump to the article you're fixing. |
| **Text correction** `…/texts/{sha}/correction` | Line diff between the source's text and the correction | — |
| **Add Document** `/documents/new` | Manual fields, then an upload straight to S3 | — |

### 3.3 What we have that Pasal.id doesn't show

We keep these, and nothing in the plan weakens them:
- the publish gate, with "last good version" semantics;
- each field compared across sources;
- conflicts between a correction and a later source change;
- curator corrections with reasons and authors;
- suppression;
- ingestion health;
- Islamic-finance instruments with their own ID schemes (OJK, BI, DSN-MUI fatwas).

## 4. The gaps

The test for every row: *is it missing in the console, even though the platform has it, or missing in the platform too?* Effort: **S** is under 2 days, **M** is 3–5 days, **L** is over a week.

| # | Pasal.id has | We have | The gap | Missing where | Value to a curator | Effort |
|---|---|---|---|---|---|---|
| G1 | Every article rendered in full, with a table of contents and anchors | An outline of labels and headings; 400 at most; first main text only | **No way to read the parsed articles.** To judge whether the parser cut Pasal 5 right, a curator opens a raw text file and searches it. | Console and API: the API returns no provision bodies, and `registry.provision` keeps offsets only | **Highest.** This is the core of "is the structure right?" | M |
| G2 | The PDF beside the text | "Open File" in a new tab | No side-by-side view of the source PDF and the parsed text, and no jump to the article's page | Console only: `page_start` and the signed file link already exist | High: OCR and structure errors show up when the two are compared | S |
| G3 | Pohon peraturan: Mengubah / Diubah oleh / Dicabut oleh | Two tables of raw relation types | **Lineage isn't shown as lineage.** "Amended by" has to be read from the "Cited by" rows whose type is `amends`. Article-level targets show as `pasal-i → pasal-115`. | Console only: every link and its direction are in `links_in` / `links_out` | High: status and validity decisions depend on it | S |
| G4 | Status badge plus "Rincian status" | A status badge and a status-history table | **Why** a status holds isn't explained: whether it comes from the source or from links, and which document caused it | Console mostly. `status_event.source` exists, but the event isn't tied to the link that caused it. | Medium | S |
| G5 | Per-article amendment notes (Pasal.id shows these only partly) | A "Changed {date}" badge in the outline | Doesn't say **by what**, and doesn't link to the new wording (`pasal-i/pasal-N` in the amending document) | API: the provision's `valid_to` and the incoming `amends` link aren't joined in the view | High for amended instruments | S–M |
| G6 | Search that returns articles, with excerpts | Metadata `ILIKE`, capped at 50 | **No search in the text.** You can't find "which POJK says *wakaf uang*", or the article that holds a phrase. | API and database: no text index exists (no `tsvector` and no `pg_trgm` in any migration) | High | M |
| G7 | Filters by type, year and status, with counts and paging | None | No filters, facets or paging | API and console | Medium–high, once G6 exists | S (with G6) |
| G8 | Browse by type, then year, with counts | Counts per issuer on the overview | **No browsing.** "Show me every SEOJK from 2021" is impossible without guessing a query. Coverage gaps (a missing number in a series) go unseen. | API and console. The index `document_issuer_family_idx (issuer, family, year)` already exists. | High for coverage checks | S–M |
| G9 | Tautan / Salin per article; a page per article | None | No link to an article that can be shared in a review note. No copy of a formal citation ("Pasal 5 ayat (1) POJK Nomor 10/POJK.05/2019"). | Console | Medium; cheap once G1 exists | S |
| G10 | Verification tiers, explained | The facts are scattered: gate result, approved as is, corrected, `method` (OCR or text layer), `fetched_at` | No single **provenance** summary saying how far this text can be trusted | Console, plus a small API field | Medium | S |
| G11 | Corrections tied to an article (`/koreksi/[nodeId]`) | Text correction of the whole text | You can't start a correction from an article: "Correct this article" should open the editor at its `char_start` | Console. The offsets index the parsed text, which is the effective one. | High with G1: it closes the loop of reading, spotting and fixing | S |
| G12 | References inside the document as hyperlinks ("Pasal 19 ayat (2)") | References between instruments only (`domain/citations.py`) | No references inside a document | Parser (domain) | Low for curation | M |
| G13 | Reports from readers flow into an admin queue (`report_issue`, "Ada masukan?") | Review queues fed by the platform only | Whoever uses the assistant can't report a wrong article to the curators | API and the assistant side | Depends on the product. **Needs a decision**, §7. | M |
| G14 | LN/TLN numbers; place enacted | Not in the contract | Data, not UI | Contract and connectors | Low | — |
| G15 | Version or history view (Pasal.id doesn't have one either) | Older text versions are kept but not shown | Can't compare a new source text with the previous one | API and console | Medium, after G1 | M |

## 5. What we leave out, and why

| Pasal.id feature | Why not in the console |
|---|---|
| Reading quota, public accounts, Save (Simpan) | The console has a few signed-in curators. Nothing is gated per reader. |
| Public discovery API, MCP server, access tokens | Serving readers and AI clients is the knowledge and retrieval layer's job: it reads `published.*`. The curation API is private by design (ADR-2 in `docs/curation-web-separation-design.md`). If the assistant ever needs an MCP surface, that belongs to the retrieval layer, as its own design. |
| English UI toggle, FAQ blocks, SEO, "not legal advice" disclaimer | They serve a public audience. The language of the console's labels is a separate decision, §7. |
| Court decisions (Putusan MK) | Coverage, not a console feature. Adding MK decisions would be a new connector and a new family. |
| Consolidated text | Pasal.id doesn't have it either ("Konsolidasi belum tersedia"). G5 is the cheaper step toward it. |

## 6. The plan

Four releases, ordered by value per effort. Each can ship and help curators on its own. Every release follows the same rules as before:
- the console never reads data directly;
- every new read is a curation API endpoint with a read model in `application/views.py` and a query in `adapters/postgres/views.py`;
- the OpenAPI contract is regenerated and checked by `test_api_contract.py` and `npm run api:check`;
- tests come first in both repositories.

### Release A: understand the lineage (console only, about 1 week)

The data is already in `DocumentView`, so these are presentation changes, with tests on the pure rules in `src/lib/`. Closes **G3, G4, G10**, and the console half of **G2**.

1. **Lineage panel**, replacing the Links section's two tables. Links are grouped by legal meaning and direction:
   - Mengubah / Diubah oleh (`amends`);
   - Mencabut / Dicabut oleh (`revokes`);
   - Mencabut sebagian / Dicabut sebagian oleh (`partly_revokes`);
   - Menggantikan / Digantikan oleh (`supersedes`);
   - Dasar hukum / Menjadi dasar hukum bagi (`legal_basis`);
   - Melaksanakan / Dilaksanakan oleh (`implements`);
   - fatwa adoption and changes;
   - other references.

   Each row shows the other document's citation, its date, and the articles involved, in readable form ("Pasal 115, as worded by Pasal I"). A pure function `lineage(links_in, links_out)` in `src/lib/` maps relation and direction to a group and its label.
2. **Status explained.** Beside the status badge: where the status comes from (the source, or links) and the latest event that set it, linked to the document that caused it when one did. Its test: the effective status and its history give one sentence.
3. **Provenance summary** at the top of the page, as a short list drawn from fields that already exist:
   - acquired from (connectors);
   - the main text's method (text layer, OCR or source);
   - the gate result;
   - approved as is, or corrected, by whom and when;
   - last fetched.

   The tiers are named for our facts. We don't import Pasal.id's.
4. **The source PDF, inline.** "View beside" opens the main file's signed link in a panel next to the Structure section, on wide screens. On phones, it keeps opening in a new tab.

**Done when:**
- a curator can answer "what amended this, and is it still in force?" from the top of the page;
- the e2e fixture gains an amending pair, and a spec asserts "Diubah oleh".

### Release B: read the document as parsed (API and console, about 1.5 weeks)

Closes **G1, G2** (jump to a page), **G5, G9, G11**. This is the release that changes curators' daily work the most.

1. **API**: `GET /api/v1/documents/{id}/texts/{sha}/provisions`, returning the tree with each provision's **body**. The body is cut from the text's effective bytes using the registry's offsets, the same way publishing cuts it. Results are paged by top-level unit (`?after=<address>&limit=`), so a 1.8 MB text never travels in one answer. Each article also carries:
   - its `valid_to`;
   - **what changed it**: the incoming `amends`, `revokes` or `partly_revokes` link whose `to_address` is this provision or its parent, with the amending document's citation and the address of the new wording.

   `ProvisionRow` gains `body` and `changed_by`. A use-case-free query, like every other read. A `TextProvisions` port is used only if the blob read needs one.
2. **Reader tab** on the document page, `/documents/{id}/read?text={sha}`. For each current text, not only the first:
   - a table of contents, BAB then Pasal, collapsible, sticky on wide screens;
   - every article in full, with ayat, page number and anchor (`#pasal-5`);
   - the Penjelasan in its own group, linked from its article ("Penjelasan Pasal 5");
   - the structure problems shown on the articles they concern. Gaps are marked between neighbours ("Pasal 7 is missing here").

   Long texts use `content-visibility` and load in pages as the curator scrolls. The editor's 1.8 MB fixture is the e2e test.
3. **Per-article actions:**
   - **Link**: copies the console URL with its anchor;
   - **Copy citation**: a formal citation, from a pure `formalCitation(provision, document)`, unit-tested on POJK, PBI, UU and fatwa examples;
   - **Page n**: opens the inline PDF at that page with `#page=n`;
   - **Correct**: opens the editor scrolled to and selecting `char_start`–`char_end` (`?at=` on the edit route; CodeMirror `scrollIntoView`).
4. **"Changed by" on amended articles**: "Changed on 12 May 2021 by POJK 12/2021, Pasal I item 3", linked to that address in the amending document's reader.
5. The outline in the Structure section is replaced by a link into the reader. The 400 cap goes away.

**Done when:**
- a curator can go from a held document to the article with the problem, compare it with its PDF page, and open the editor at that article, without a raw file;
- the large-text e2e still opens in under a second.

### Release C: find and browse (API, database and console, about 1.5–2 weeks)

Closes **G6, G7, G8**.

1. **Text search across articles.** Migration `0012_provision_search.sql`: a generated `tsvector` column on `published.provision.body`, using the `simple` configuration because Postgres ships no Indonesian stemmer, with a GIN index. Also a `pg_trgm` index on `registry.document (citation, title)` for typo-tolerant metadata matches.
   - `GET /documents?q=&issuer=&family=&year=&status=&state=&page=` returns document hits and **article hits with an excerpt** (`ts_headline`).
   - It is paged, with counts per facet.
   - The 50-result cap goes away.

   **The limit to accept, or decide against** (§7): article text is searchable only for documents that are published. A held document that was never published is still found by its metadata.
2. **Search page:**
   - results in two kinds: documents and articles, with the article linking to `read#pasal-n`;
   - filter chips (issuer, family, year, status, and the publishing state: published, held, suppressed), with counts;
   - paging;
   - the query and filters kept in the URL.
3. **Browse** `/documents/browse/{issuer}/{family}?year=`:
   - every document of a series by year, newest first, with status and publishing state;
   - **gaps in the numbering marked**, from a pure `numberGaps(numbers)`. For example, SEOJK 2021: 1–14, then 16–30, and "15 missing". That turns browsing into a coverage check, which Pasal.id doesn't do.

   The overview's "documents by issuer" links into it.

**Done when:**
- "wakaf uang" finds the fatwa and the article;
- "SEOJK 2021" lists the year with its gaps;
- the e2e covers a filtered search and a browse page.

### Release D: references inside a document

- **G12, references inside a document.** Parser work: references such as "Pasal 19 ayat (2)" within the same document become provision-level links. The reader shows them as links to the article. About 1 week.
- **G15, text versions, and G13, reports from outside:** dropped for now (§7). Revisit later.

### Summary

| Release | Closes | Where | Size | Why in this order |
|---|---|---|---|---|
| A: lineage | G3, G4, G10, G2 (part) | Console | ~1 wk | The data is already loaded; no contract change; quick visible win |
| B: reader | G1, G2, G5, G9, G11 | API and console | ~1.5 wk | The biggest change to daily work: read, compare and fix in one place |
| C: find and browse | G6, G7, G8 | Database, API and console | ~1.5–2 wk | Needs an index and a migration; most useful once the reader exists to land on |
| D: references inside a document | G12 | Parser, API and console | ~1 wk | Builds on the reader |

## 7. Decisions (2026-10-20)

1. **Text search scope: published only.** Article text is searched in `published.provision`. Held documents that were never published are still found by their metadata.
2. **Release D: only G12** (references inside a document). G13 (reports from outside) and G15 (text versions) are dropped, to revisit later.
3. **Labels: Indonesian names** for legal relations and units (Mengubah, Diubah oleh, Pasal, Ayat, Penjelasan …). The rest of the interface stays in English.

## 8. Built (2026-10-20)

| Release | What was built | Where |
|---|---|---|
| A: lineage | The **Lineage** section groups links by meaning and direction, in Indonesian (Diubah oleh, Mencabut …), one entry per document with its articles and effective date. The header has a **Provenance** list: where the status comes from (correction, source, or the document whose link implies it), acquisition, main text, checks. Status History names each derived change's cause. | Platform: `LinkRow.document_citation`, `effective_on`; `StatusRow.caused_by`, `caused_by_citation` (the event's link). Console: `src/lib/legal.ts`, `LineageSection`, `Provenance` |
| B: reader | `/documents/{id}/read`: every provision in full, read once in its innermost provision; heading lines shown as headings; a table of contents (folded on phones); gaps in the article numbering marked; "Diubah oleh … · Read the new wording" on changed articles; per article **Copy Link**, **Copy Citation** (formal: "Pasal 5 ayat (1) POJK …"), **Page n**, **Correct** (the editor opens on that article, selected); page markers shown and linked; the PDF beside the text on wide screens. Texts over 200,000 characters are read in parts (the 1.8 MB fixture opens in ~0.6 s). | Platform: `domain/reading.py`, `application/reading.py` (`ReadText`), `reading_source()`, `GET /documents/{id}/reading`. Console: `src/components/reader/`, `src/lib/reading.ts` |
| C: find and browse | Search finds documents by metadata **or published wording**, and lists the matching **articles** with their words marked; filters for issuer, family, year, status and publishing state, each with counts; paging; with no query it lists every document the filters leave. **Browse** lists each series, and a series by year with the numbers not held marked. | Platform: migration `0012_provision_search.sql`; `search()`, `series()`, `series_page()`; `GET /documents` (new shape), `/series`, `/series/{issuer}/{family}`. Console: `/documents`, `/browse`, `src/lib/search.ts` |
| D: references inside a document | "Pasal 19 ayat (2)", "ayat (1)" (of the article it is in, or of the one just named) become links in the reader; another instrument's articles ("Pasal 8 … Undang-Undang Nomor 21 Tahun 2011") and an amending regulation's quoted articles are left alone. | Platform: `domain/cross_references.py`; each read passage carries its references (UTF-16 offsets). Console: `linkedPieces()` |

**Departures from the plan:**
- The inline PDF moved from Release A to the reader (B), where it sits beside the text it is compared with.
- No `pg_trgm` index: 2,600 documents are matched by metadata fast enough without one.
- Article search is one query a search: the matching documents, the count and the page come from its result; only the shown articles' excerpts are computed. Measured on a copy of the live data: 0.14–0.25 s for typical queries, 0.47 s for the commonest word ("bank", 39,498 articles).
- G12's references are found when a part is read, not stored as links: no schema or contract change for the knowledge layer. The parser can store them later if retrieval needs them.

**To deploy:** apply migration 0012 (`metamorph db migrate`: it adds a stored column to `published.provision` and indexes it, about 11 s on the live data's size), then rebuild and restart the compose `api` and `web` services. The new search fails until the migration is applied.
