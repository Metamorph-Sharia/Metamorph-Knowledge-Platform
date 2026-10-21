# Plan: MinerU extraction, clean text and full legal structure

**Date:** 2026-10-20 · **Status:** steps 1–7 built (`packages/metamorph-pdf-text`; contract 2.1; migrations 0013 and 0014; parser 6; the retrieval units and edges; the four connectors wired behind `METAMORPH_PDF_ENGINE`; the MinerU service and its check); steps 9–12 to do · **Branch to start from:** `pdf-printed-lines`

## Context

Every connector reads its official PDFs with PyMuPDF. Three of them also run their own OCR:
- **BPK:** ocrmypdf + Tesseract, only on pages with no text layer.
- **BI:** PyMuPDF's `get_textpage_ocr(language="eng", dpi=150)`.
- **DSN-MUI:** `tesseract -l ara` for Arabic quotations.

The text that results is still noisy where it matters:

| Connector / method | Main texts | Pages | Median out-of-vocabulary words | Noisy texts (pages) |
|---|---:|---:|---:|---:|
| DSN-MUI text layer | 164 | 1,355 | 23.6% | 164 (1,355): Arabic quotations come out as glyph junk (`動物乃らθrc′′`), Latin is letter-spaced (`Dew an Syar iah`) |
| BPK text layer | 92 | 3,752 | 3.9% | 15 (713): the publisher's own OCR layer, scrambled reading order |
| OJK text layer | 92 | 10,499 | 2.4% | 5 (1,215) |
| BI text layer | 1,231 | 29,141 | 0.1% | 8 (107) |

The figures are from `Metamorph-EDA/2026-10-20-pdf-printed-lines` (main texts only). Repeated page furniture adds to the noise. For example, the State Secretariat's print serial **`SK No 123456 A`** appears on about 16,000 lines across 30 BPK texts, and OCR mangles it as `SK No llN C` and `SK No IN C`.

**Decisions (user, 2026-10-20):**
1. Adopt MinerU in every connector that reads PDFs: BPK, BI, OJK and DSN-MUI, **without a pilot**. The first full re-extraction is the validation run, judged against the criteria in [Validation](#validation).
2. The goal is clean, readable text. It must keep every *Bab*, *Bagian*, *Paragraf*, *Pasal*, *Ayat* and each lettered or numbered item apart, for the knowledge graph, the embeddings and RAG retrieval.

**Out of scope:**
- OJK's texts taken from its website HTML (`method=source`). They are already the issuer's own text.
- Embedding, the vector index and the retrieval API. These stay in the Knowledge and Retrieval layer, as [data-source-management-plan.md](data-source-management-plan.md) decided. This plan delivers the units and context that layer embeds.

## Principles

1. **Ownership doesn't move.**
   - Connectors turn files into text, and now clean it.
   - The platform turns text into structure, links and published rows.
   - The Knowledge layer turns published rows into vectors and graph queries.

   MinerU sits inside the first step only.
2. **Remove noise, never rewrite wording.** Cleaning may only:
   - delete page furniture;
   - join a word hyphenated across a line ("perusa-" + "haan");
   - normalise whitespace.

   Every other character is the engine's reading of the page: the PDF's own characters on born-digital pages, the OCR's on scans. No spelling correction, and no LLM rewriting.
3. **Structure is carried by line layout, as now.** The contract stays plain text with `<!-- page N -->` markers, so the platform's parser stays the one owner of structure. MinerU's output is rendered into the layout the parser expects (one heading per line, each paragraph and item starting its own line). No MinerU type crosses the contract.
4. **Explicit engine, no silent fallback between engines.** A text records which engine read it. A MinerU outage fails the task, so it can be retried. It never quietly produces a PyMuPDF text, because the text's sha256 would then change back and forth between runs and re-parse every document. The per-page fallback in step 4 of the pipeline is different: it is a decision recorded in the text's provenance.
5. **Reversible.** `METAMORPH_PDF_ENGINE=pymupdf` restores today's extraction in every connector, through the same route as `METAMORPH_PDF_LINES`. Every connector already has a re-extract command to apply either setting to the files it holds.

## MinerU: what we use

Pinned to **`mineru==4.0.12`** (released 2026-10-11) and its matching `docvortex==0.5.16`. 4.0 had eight patch releases in three weeks, so never use an unpinned upgrade.

| Feature | How we use it |
|---|---|
| V1 HTTP API (`mineru-kit api-server`): `POST /v1/tasks`, `GET /v1/files/{id}/content`, `GET /v1/health` | One shared service that every connector calls. Asynchronous tasks, because a 1,187-page BPK file outlasts a synchronous wait. |
| Tiers | `standard` (small models plus the VLM) for `main` files. `basic` (small OCR and layout models) for `annex`, `faq`, `guide` and `abstract` files. |
| `ocr_mode` | `auto` by default. Its classifier sends a document to OCR when the text layer is image-backed (publisher OCR) or decodes badly (CID fonts without a Unicode map, a Latin font decoding as CJK). Forced `ocr` when our own page-quality check (see [Cleaning](#cleaning-the-text)) flags a text layer `auto` kept. |
| `middle_json.json`: ordered `pages[]` with `page_idx` and blocks with a type, text and bbox | The only output we read. It's rendered to plain text by our adapter. We never use the Markdown, HTML or LaTeX. |
| Discarded block types `page_header`, `page_footer`, `page_number`, `page_aside_text` | The first noise filter (see [Cleaning](#cleaning-the-text)). `page_footnote` is kept, because footnotes are wording. |
| `sha256sum` on upload | MinerU reuses a result it already holds. |
| `--api-key`, `--concurrency` | Required in every deployment. Concurrency is sized to the machine. |

All 2,998 official files are within the 200 MiB per-file limit (the largest is 81 MB).

**License:** MinerU Open Source License, which is Apache 2.0 plus conditions. A separate license is needed only above 100M monthly active users or USD 20M monthly revenue. Any online service to third parties must state visibly that it uses MinerU (step 12). The licenses of the model weights must be checked before production (see [Risks](#risks-and-open-questions)).

## Architecture

```
┌ Knowledge & Retrieval layer (other repo) ─ embeds published.provision_unit, walks published.link ┐
│                                                                                                   │
│ ┌ Platform ─ domain/structure (parser 6) → published schema (+ provision_unit view) ────────────┐ │
│ │                                                  ▲ contract v2.1 bundle: plain text + markers │ │
│ │ ┌ Connector (BPK, BI, OJK, DSN-MUI) ─ its use case calls its TextExtractor port ───────────┐ │ │
│ │ │ ┌ shared package metamorph-pdf-text ─────────────────────────────────────────────────┐  │ │ │
│ │ │ │ domain:      Page, Block, BlockKind, clean(), render(), aligned(), page_quality()  │  │ │ │
│ │ │ │ application: ExtractPdf use case; ports LayoutReader, ResultCache                  │  │ │ │
│ │ │ │ adapters:    MinerUReader (HTTP V1), PyMuPdfReader, FileResultCache                │  │ │ │
│ │ │ └────────────────────────────────────────────────────────────────────────────────────┘  │ │ │
│ │ └──────────────────────────────────────────────────────────────────────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
infrastructure: MinerU api-server (macOS host process in development, NVIDIA container in production)
```

### The shared package `packages/metamorph-pdf-text`

The package sits beside `metamorph-contract`, and connectors depend on it by path, the way they depend on the contract. Without it, the four connectors would each copy the renderer, the cleaner, the verifier and the HTTP client. It is not `metamorph-contract`, because that package must stay a dependency-light contract (jsonschema only), and this one brings `httpx` and `pymupdf`.

The package follows the dependency rule: each ring imports only rings inside it.

**Domain** (`domain/`, pure Python: no I/O, no MinerU, no PyMuPDF):
- `Block(kind: BlockKind, text: str, bbox: BBox)` (its page is the `Page` holding it) and `BlockKind`: `title | text | list_item | table | footnote | header | footer | page_number | aside | image | formula`.
- `Page(number: int, width: float, height: float, blocks: tuple[Block, ...])`.
- `clean(pages) -> CleanedPages`: the noise rules. It returns the pages kept and a `Removal` log: rule, page, text.
- `render(pages) -> list[str]`: one plain-text string per page, laid out for the parser (see [Text layout](#text-layout-the-contract-between-extraction-and-parser)).
- `aligned(candidate, reference) -> Alignment`: a word-for-word comparison, generalised from the printed-lines check. It reports the words missing and the words added (a misread word is one of each), so reordering is free.
- `page_quality(text) -> PageQuality`: out-of-vocabulary words, OCR confusions, damaged headings, private-use and CJK-in-Latin ratios, characters per page. The same measures as the EDA, moved from scripts into code.

**Application** (`application/`):
- **Ports:**
  - `LayoutReader.read(pdf: bytes, request: ReadRequest) -> list[Page]`
  - `ResultCache.get/put(key) -> list[Page] | None`
- **Use case** `ExtractPdf(reader, reference_reader, cache).run(pdf, role) -> ExtractedPdf`:

  ```
  ExtractedPdf
    pages: list[str]         one string per page, ready for join_pages
    method: text_layer | ocr
    extraction: Extraction   engine, version, tier, ocr_mode, pages_ocrd, pages_fallen_back
    removals: list[Removal]  for the audit report, not for the bundle
  ```

- **Policy** `request_for(role, quality) -> ReadRequest` maps a file's role and its text-layer quality to a tier and an `ocr_mode`.

**Adapters** (`adapters/`):
- `MinerUReader`: the V1 client. It uploads with `sha256sum`, submits a task, polls with a bounded budget and downloads `middle_json.json`. It then **translates** MinerU's block types into `BlockKind`, so MinerU's JSON never leaves this module. Its errors are `ExtractionUnavailable` (retryable) and `ExtractionFailed`.
- `PyMuPdfReader`: blocks from `get_text("dict")`, with lines joined by `printed_text`. It serves as the `pymupdf` engine and as the alignment reference for pages MinerU read from the text layer.
- `FileResultCache`: `{cache_dir}/{pdf_sha256}/{mineru_version}-{tier}-{ocr_mode}.json`, so a re-extract or a rollback-and-forward never re-runs the model.

**As built in step 2:**
- A reader returns a `Reading(pages, ocr_mode)`, where `ocr_mode` is the mode it resolved (`txt` or `ocr`). MinerU decides per document.
- `ExtractPdf(reader, text_layer, cache, vocabulary)`: `vocabulary` (the lowercased words of clean texts) feeds `page_quality`.
- During verification, each reading is cleaned on its own, and a word only one of them removed by a logged rule doesn't count as missing.
- An OCR'd page falls back when it is noisy and the text layer isn't, or when it is empty and the layer isn't. A page with an empty layer (a scan) keeps its OCR.
- The cache key is `CacheKey(pdf_sha256, engine, version, request)`.

**The rollback engine is not `ExtractPdf`.** Cleaning and rendering change the text, so `METAMORPH_PDF_ENGINE=pymupdf` must make `from_environment` return each connector's existing extraction (`printed_text` per page) unchanged. That is what keeps the rollback byte-identical (step 3's done criterion). `ExtractPdf` always pairs the layout reader with `PyMuPdfReader` as its text layer.

**As built in step 3:**
- **MinerU's V1 API, as its 4.0.12 source defines it** (`mineru/parser/api_server.py`):
  1. `POST /v1/uploads` with `filename`, `bytes`, `mime_type` and `sha256sum`. A file the service already holds comes back `completed`.
  2. Otherwise `PUT` the bytes to `upload_url`, then `POST /v1/uploads/{id}/complete`.
  3. `POST /v1/parse/jobs` with `files[{source: {type: file_id}}]`, `tier`, `ocr_mode` and `output_formats: ["middle_json"]`.
  4. Poll `GET /v1/parse/jobs/{id}` until it is done.
  5. `GET /v1/files/{id}/content`.

  The request models forbid extra fields, so the requests carry only these. A server started with `--tier standard` also serves `basic`. The resolved mode is `extensions.mineru.parse_mode`, and bboxes are normalised to 0–1, so MinerU pages are 1 × 1.
- **The version is pinned.** `MinerUReader.version` is `4.0.12+t1`, MinerU's version plus the translation's revision. A service running another version is refused before it is sent a file.
- **The vocabulary** ships as `adapters/vocabulary.txt`: 13,553 words from 2,091 clean OJK website and BI text-layer texts. `scripts/build_vocabulary.py` rebuilds it.
- **Composition:** `wants_mineru(environ)` decides between the engines. `from_environment(environ)` builds `ExtractPdf` and needs `METAMORPH_MINERU_URL` and `METAMORPH_MINERU_CACHE`. `SETTINGS` lists the four names an orchestrator passes on.

**Composition:** `metamorph_pdf_text.from_environment(environ) -> ExtractPdf` reads `METAMORPH_PDF_ENGINE`, `METAMORPH_MINERU_URL`, `METAMORPH_MINERU_API_KEY`, `METAMORPH_MINERU_CACHE` and `METAMORPH_PDF_LINES`. Each connector calls it once in its composition root.

**Why the two ports are worth having:**
- `LayoutReader` has two real implementations: MinerU, and PyMuPDF for both the rollback engine and the alignment reference.
- `ResultCache` lets the tests run without a model and without the network.

No other interfaces are added.

### Where each connector plugs in

The connector's own boundary stays as it is. Only its adapter behind that boundary changes.

| Connector | Today | After |
|---|---|---|
| **BPK** | Port `application/ports.py::TextExtractor`. Wiring: `ArchiveTextExtractor(OcrTextExtractor(PdfTextExtractor))` | New adapter `adapters/extraction/mineru.py::MinerUTextExtractor(TextExtractor)` wraps `ExtractPdf`. `wiring.build_extractor` chooses it when the engine is `mineru`, and `ArchiveTextExtractor` still unpacks ZIP annexes. `OcrTextExtractor` stays for the `pymupdf` engine until step 11. |
| **BI** | `src/pipeline/extractor.py::read_pages` (PyMuPDF plus English Tesseract) | `read_pages` delegates to `ExtractPdf`, built once in `src/config.py`. `reextract_records` and `reextract_database` pick it up unchanged (both stores, see `bi-corpus-storage`). |
| **OJK** | `pdf_text.py::extract_text(data, *, printed_lines)` | `extract_text` delegates to `ExtractPdf`. The HTML source texts are untouched. |
| **DSN-MUI** | `dsn_ingest/extract.py::pdf_to_pages`, which strips Arabic, plus `scripts/ocr_arabic.py` (`tesseract -l ara`) | `pdf_to_pages` delegates to `ExtractPdf`. The Arabic-script lines MinerU reads are split off into `data/dsn/ocr/<sha>.ara.txt`, the same file as today, so the contract text stays Latin as now. `ocr_arabic.py` is kept as the `pymupdf`-engine path. |

### What crosses each boundary

| Boundary | Data |
|---|---|
| MinerU → `MinerUReader` | MinerU's `middle_json`. It stops here. |
| `LayoutReader` → `ExtractPdf` | `list[Page]` of our `Block`s |
| `ExtractPdf` → connector | `ExtractedPdf`: plain page strings, method, `Extraction` |
| Connector → platform | Contract v2.1 bundle: text blob with page markers, `TextRef` with the optional `extraction` |
| Platform → Knowledge layer | `published.*` rows and the new `published.provision_unit` view |

## The extraction pipeline, per file

1. **Plan the request.** `request_for(role, quality)`:
   - Tier: `main` → `standard`, everything else → `basic`.
   - `ocr_mode` starts as `auto`.
   - It becomes `ocr` when more than 20% of the sampled pages of the PyMuPDF text layer fail `page_quality`. This catches a publisher OCR layer that MinerU's classifier kept.
2. **Read.** From the cache, or from `MinerUReader`.
3. **Clean.** Run `clean(pages)`; see the next section.
4. **Verify each page, when MinerU kept the text layer** (`ocr_mode` resolved to `txt`):
   - Align the page's words with `PyMuPdfReader`'s words, after the same cleaning.
   - The page passes when no word is missing or changed. Words removed by a logged furniture rule don't count. Reordering is allowed: fixing the reading order is one of the reasons to use MinerU.
   - A page that fails falls back to PyMuPDF's cleaned page, and it is counted in `pages_fallen_back`. This is what protects born-digital wording from the VLM.
5. **Verify each page, when MinerU OCR'd it:**
   - It must not score worse than the text layer on `page_quality`.
   - Its page must not be empty when the image has text, measured by MinerU's own layout block count.
   - If it fails, it falls back to the text layer, and that's counted.
6. **Render.** Turn each page into a string with `render(pages)`, then join them with `join_pages`.
7. **Label.**
   - `method = ocr` if any page was OCR'd, else `text_layer`.
   - `extraction = {engine: "mineru", version: "4.0.12", tier, ocr_mode, pages_ocrd, pages_fallen_back}`.

The fallback in steps 4 and 5 is per page, it is deterministic for a given cache entry, and it is recorded. That is what separates it from the silent engine switch that principle 4 forbids.

## Cleaning the text

The rules run in this order on `Block`s, each with its bbox and page. Every removal is logged.

| # | Rule | Removes | Guard (never removed) |
|---|---|---|---|
| 1 | MinerU furniture | blocks typed `header`, `footer`, `page_number`, `aside` | A block whose text matches a structure heading or an item marker: `^(BAB\|Bagian\|Paragraf\|Pasal\|Ayat)\b`, `^\(\d+\)`, `^[a-z]\.`. A block in the top band that is a document's first title. |
| 2 | Print serial | `SK No` followed by at most three short alphanumeric tokens holding a digit, none a word of 4+ letters: covers the OCR forms `SK No l19tt6l C`, `SK No I l29l2c`, `SK No LIS5611A`, `SK No 067-569 A` | not `SK Nomor …`, not `SK No 12 Tahun 2020 …` |
| 3 | Repeated band lines | At the edge (first or last 3 lines) of a block in the top or bottom 12% of the page: **a printed page number** (`3`, `- 3 -`, `Halaman 3 dari 10`) when it follows the pages at the document's offset from the PDF's page number, on at least 30% of the pages and 3; **any other line** that recurs, normalised (numbers → `#`, case, spaces and punctuation folded) and fuzzily grouped (`PRES I DEN` = `PRESIDEN`, `INDONESTA` = `INDONESIA`), on as many pages, except at its first place | A line that opens with a structure word (incl. `Lampiran`) or an item marker, or ends like a sentence (`Cukup jelas.`); the first page's head; numbers that don't follow the pages (a table's row numbers and codes) |
| 4 | Catchwords | The last line of a page that repeats the first words of the next page and ends with `...` or `…` (`Pasal 5 . . .`, `b. bahwa ...`) | none |
| 5 | Hyphenation | joins `word-\nword` when the line ends in a letter followed by `-` and the next line starts with a lowercase letter | Compound forms that keep their hyphen (`badan-badan`) are rejoined with the hyphen. |
| 6 | Whitespace | collapses runs of spaces, trims lines, keeps at most one blank line between blocks | none |
| 7 | Script split (DSN-MUI only, at the connector) | moves Arabic-script lines to the `.ara.txt` side file | none |

**What cleaning never does:** correct a word, change a number, or remove a footnote, a table cell, a signature block or a "SALINAN" stamp that sits in the body. Rules 1 and 3 work by position *and* repetition, so text in the body is safe.

The platform's own furniture rules (`domain/structure/text.py::is_page_furniture`, `domain/layout.py`) stay as a safety net for texts read with the `pymupdf` engine.

## Text layout: the contract between extraction and parser

`render()` writes each page so that structure is visible from the lines alone. This is added to the "Text from a PDF" section of `CONTRACT_V2.md`:

1. **One block, one paragraph.** A block's lines are joined into one line. A blank line separates blocks.
2. **Headings on their own lines.** Each of these keeps its own line, with nothing joined onto it:
   - `BAB IV` and its title on the next line;
   - `Bagian Kesatu`, `Paragraf 2`, `Pasal 5`;
   - `MEMUTUSKAN:`, `Menetapkan:`, `Menimbang`, `Mengingat`, `Memperhatikan`;
   - a fatwa's `Pertama` / `Kedua`.

   A MinerU `title` block always renders as its own line. A text block that opens with one of these labels is split after the label.
3. **Items start lines.** These open a new line, with the marker kept at its start:
   - an ayat `(1)`;
   - a letter `a.`;
   - a number `1.`;
   - a Roman `I.`.

   MinerU's `list_item` blocks render one item per line.
4. **Tables** render one row per line, with cells joined by ` | `. They are mainly annex tables, such as KBLI lists.
5. **Reading order** is MinerU's. Two-column pages and side notes come out as single columns.
6. **Page markers.** `<!-- page N -->` opens each page, as now. Page numbers are one-based, from `page_idx + 1`.

This layout is what grammar parser 5 already expects. With it, the parser no longer depends on heuristics such as `_RULING_BESIDE` or the lone-marker joins for MinerU texts, but they remain for `pymupdf` texts.

## Preserving the full legal structure (platform, parser 6)

The parser already cuts `bab`, `bagian`, `paragraf`, `pasal`, `ayat`, `penjelasan`, `lampiran`, `romawi` and `diktum`, plus the opening (`menimbang`, `mengingat`, `memutuskan`). There are 174,622 ayat and 83,521 pasal today. What's missing for "each individual provision or clause" is the items inside them, which `cross_references.py` currently says "aren't provisions".

**Changes in `domain/structure/` (`PARSER_VERSION = "6"`):**

1. **New kinds `huruf` and `angka`:**
   - **Addresses:**
     - `pasal-5/ayat-1/huruf-a`
     - `pasal-1/angka-3`, the numbered definitions of Ketentuan Umum
     - `pasal-1/angka-3/huruf-b`
     - `menimbang/huruf-a`
     - `mengingat/angka-2`
     - `romawi-ii/angka-3`
     - `diktum-kedua/angka-1`
   - **Nesting** follows marker style in order of appearance, the rule `domain/layout.py` already uses for depth. A letter under a number is a child of that number.
   - A letter or number in an amending article's quoted text belongs to the quoted article (`pasal-i/pasal-115/ayat-2/huruf-a`).
   - Elucidations mirror the body: `penjelasan/pasal-5/ayat-1/huruf-a`.
2. **Ranges stay nested.** An item's `char_start`/`char_end` lie inside its parent's, so `reading.py` still reads each character once, in its innermost provision.
3. **Quality checks** (`quality.py`). *Not built, by measurement: see step 5's row.* As planned:
   - Letters run `a, b, c…` and numbers run `1, 2, 3…` within a parent.
   - A gap is a structure problem, as for ayat.
   - Quoted partial lists in amendments are exempt, as ayat are today.
4. **Cross-references** (`cross_references.py`): `Pasal 3 huruf a` and `Pasal 1 angka 2` now link to `pasal-3/huruf-a` and `pasal-1/angka-2`, falling back to the article when the item isn't found.
5. **Headings:** `bab`, `bagian` and `paragraf` keep their title in `heading`. This is unchanged, but it is checked for MinerU texts, where the title is a separate `title` block.

## Preparing for the knowledge graph and RAG

The platform publishes; the Knowledge layer embeds. These additions give that layer clean units and the context to embed them with, without the platform doing the chunking.

### `published.provision`: new columns

| Column | Meaning |
|---|---|
| `heading_path` | `text[]`, the labels and titles from the root down, e.g. `{"BAB II PERIZINAN", "Bagian Kesatu Umum", "Pasal 5", "(1)"}` |
| `depth` | 0 at a root provision |
| `ordinal` | position among its siblings, for stable ordering |
| `wording` | `body` without page markers and with its own heading lines removed, the same reading as `domain/reading.py` (named `body_clean` in the first draft) |

### New view `published.provision_unit`: one row per retrieval unit

- **What a unit is.** It is the smallest provision that has its own wording:
  - an ayat;
  - a huruf or angka with wording;
  - a pasal without ayat;
  - a diktum;
  - a penjelasan entry.

  Group headings (bab, bagian, paragraf) are context, not units.
- **Columns:**
  - `document_id`, `address`, `kind`, `heading_path`, `wording`, `pages`;
  - document metadata: `issuer`, `family`, `number`, `year`, `title`, `status`, `effective_on`;
  - `elucidation_address`, the matching `penjelasan/…`;
  - `text_sha256` and `parsed_with`, so an index knows when to re-embed (through `change_log`).
- **Recommended embedding input** (documented in `published-schema.md` for the Knowledge layer): `"{citation}, {heading_path joined by ' › '}\n{wording}"`. An over-long unit (a definitions article) is split by its items, which are units themselves after parser 6.

### Graph edges in `published.link`

`published.link` keeps the edges it has (`cites`, `amends`, `revokes`, `legal_basis`) and gains:

| Edge | From → to | Source |
|---|---|---|
| `contains` | parent provision → child provision | `parent_address` (already in data, now exposed as edges) |
| `refers_to` | provision → provision in the same document | `cross_references.py`, now down to huruf/angka |
| `elucidates` | `penjelasan/X` → `X` | address mirroring |
| `cites` | provision → document or provision | `citations.py`. The citing provision's address is kept, so an edge starts at the ayat that cites. |

`docs/published-schema.md` documents each addition. They're additive, so existing readers don't break.

## Contract v2.1 (additive)

- `TextRef.extraction`, optional:
  - `engine`: `pymupdf` or `mineru`
  - `engine_version`
  - `tier`
  - `ocr_mode`
  - `pages_ocrd`
  - `pages_fallen_back`
- `method` keeps its enum: `text_layer` when every kept page used the PDF's characters, `ocr` when any page was OCR'd.
- Schema files: `normalized-document.schema.json` gains the optional property. `contract_version` accepts `"2.0"` and `"2.1"`. The schema-mirror test is updated.
- `CONTRACT_V2.md`: "Text from a PDF" gains the layout rules above and the engine setting. The checklist gains "a PDF's text is read with `metamorph_pdf_text.from_environment`".
- Platform loader: stores `extraction` on `registry.text_version` in a new nullable `extraction jsonb` column (migration), and exposes it on `published.text`.

## Deployment and dependencies

| Piece | Development (this Mac: M5, 24 GB, Docker VM 7.7 GB without a GPU) | Production |
|---|---|---|
| MinerU service | Native macOS process, because Docker on macOS has no GPU and too little memory for `standard`. `uv tool install "mineru[torch]==4.0.12"` on Python 3.12, `mineru-kit models download --tier standard` and `--tier basic`, `mineru-kit models verify`. Run with `mineru-kit api-server --host 127.0.0.1 --port 8010 --tier standard --concurrency 1 --api-key …`, kept up by a `launchd` agent (`docker/mineru/dev.mineru.plist`). | Linux + NVIDIA (≥ 8 GB VRAM, ≥ 16 GB RAM) container from a pinned image built in `docker/mineru/Dockerfile` (`mineru[full]==4.0.12`, vLLM engine). Compose profile `mineru`, with a GPU reservation and a health check on `/v1/health`. |
| Connector reach | `METAMORPH_MINERU_URL=http://host.docker.internal:8010` | `http://mineru:8010` on the compose network |
| Secrets | `METAMORPH_MINERU_API_KEY` in `.env` (the user adds it; `.env.example` documents it) | the same, from the secret store |
| Cache | `METAMORPH_MINERU_CACHE` (a volume per connector under its `data/`) | the same, on persistent storage |
| Python packages | `metamorph-pdf-text` (new): `httpx`, `pymupdf>=1.24`, `metamorph-contract`. Connectors add it by path. | the same |
| Removed at the end (step 11) | `ocrmypdf` and the Tesseract language data in BPK's image; BI's `get_textpage_ocr`; DSN-MUI's `ocr_arabic.py` path | |

**Settings:**
- `METAMORPH_PDF_ENGINE` defaults to `mineru` after step 9, and to `pymupdf` before.
- Airflow forwards `METAMORPH_PDF_ENGINE`, `METAMORPH_MINERU_URL`, `METAMORPH_MINERU_API_KEY` and `METAMORPH_MINERU_CACHE` with `CONNECTOR_SETTINGS` / `passed_on(job)` in `dags/metamorph_pipeline/jobs.py`, and `compose.yaml` lists them for each connector service.

**Throughput:**
- Re-extracting everything means about 83,000 pages: BI 39.6k, BPK 31.3k, OJK 10.5k, DSN-MUI 1.4k. The main texts are 53,000 of them.
- **Measured in step 8** on this Mac, on BPK files of 43 and 50 pages, in pages a minute:

  | Tier | Born-digital (`auto` → `txt`) | Scan (`auto` → `ocr`) | Born-digital, OCR forced |
  |---|---|---|---|
  | `basic` | 74 | 28 | 32 |
  | `standard` | 86 | 7.7 | 12 |

- **Estimate for step 9:** the text-layer census of 2026-10-21 (every held PDF, `page_quality` and `request_for`'s 20% rule, no MinerU) (`packages/metamorph-pdf-text/scripts/ocr_census.py`) counts 82,545 pages in 3,010 unique PDFs. 26,773 of them will be OCR'd: 26,105 in files whose text layer is forced to OCR (BPK 22,439, BI 2,118, DSN-MUI 1,355, OJK 193), and 668 with no text layer. On this Mac that is about 11 hours of born-digital pages plus 37–58 hours of OCR, so 2–3 days. On one AWS A10G (g5.8xlarge Spot in Jakarta, where there is no G6) it is an estimated 15–30 hours for about $13–21: see [aws-step9-guide.md](aws-step9-guide.md) (AWS CLI) or [aws-step9-console-guide.md](aws-step9-console-guide.md) (web console).
- Re-extraction runs per connector and resumes through the cache, so it can stop and restart at any point.

## Implementation steps

Each step is small, keeps all tests green, and ends in a state that can be committed. No live data is touched until step 9, and there the user runs the commands.

| # | Step | Repos | Done when |
|---|---|---|---|
| 1 | **Domain of `metamorph-pdf-text`:** `Block`, `Page`, `clean` (rules 1–6 with guards and the removal log), `render`, `aligned`, `page_quality`. Tests built from real page fixtures: an `SK No` footer, a running head, a catchword, a hyphenated word, a heading in the top band that must survive, a two-column page. | platform `packages/` | unit tests pass. An architecture test, like the platform's `tests/test_architecture.py`, fails on any import of an outer ring, of `httpx` or of `pymupdf` from `domain/` or `application/`. |
| 2 | **Application:** `ExtractPdf`, `request_for`, the ports. Tests use a fake `LayoutReader` and an in-memory cache, covering text-layer verification and fallback, OCR verification and fallback, and the method and `extraction` labels. | platform `packages/` | tests pass |
| 3 | **Adapters:** `PyMuPdfReader` (on `printed_text`), `FileResultCache`, `MinerUReader`, the shipped vocabulary, `wants_mineru` / `from_environment`. The reader's tests run against a scripted V1 service (`httpx.MockTransport`) whose responses carry MinerU 4.0.12's model fields; the Middle JSON fixture validates against `docvortex.schema.MiddleJson`. One test, marked `mineru`, runs against a live service (`METAMORPH_TEST_MINERU_URL`). | platform `packages/` | tests pass; the reference and the cleaning run over every main PDF held (1,581 files, 44,855 pages) with no unreadable file and no `SK No` line left. **Done 2026-10-20.** (The byte-identical rollback is a property of each connector's own path: checked in step 7.) |
| 4 | **Contract v2.1:** `Extraction`, `TextRef.extraction`, `CONTRACT_VERSION = "2.1"` and `READABLE_VERSIONS`. Both schemas accept 2.0 and 2.1. Also the mirror tests and `CONTRACT_V2.md`. On the platform: migration `0013_text_extraction` (`registry.text_version.extraction`, `published.text.extraction`), the loader and the publish step. | platform | Contract (85), platform (574, with the database tests) and the four connectors' suites pass; a 2.0 document and bundle still load. **Done 2026-10-20.** |
| 5 | **Parser 6:** `huruf` and `angka` kinds (`domain/structure/items.py`, one recogniser for every grammar), nested by the order marker styles appear in, up to 3 deep; the elucidation mirror (`Huruf a` / `Angka 1`); cross-references to items, falling back to the nearest provision up; item markers hang in the reader's wording at their list's depth (`list_depth`). | platform, web | **Done 2026-10-20.** Over the 4,132 snapshot texts: 249,990 items (119,688 in regulations, 55,287 in circulars, 7,440 in fatwas, 67,575 elucidated, counting by kind). No existing provision changed, except 8 fatwa rulings that parser 5 titled with their first item ("Ketujuh" titled "1. Modal usaha …"), which now have no title and their item. No problem list changed, and no wording is lost in the reader. **Item gaps are not structure problems:** measured, they would hold about 116 clean documents, mostly items lost at page breaks or lists a circular quotes from the middle. |
| 6 | **Published additions:** `heading_path`, `depth` and `wording` (the plan's `body_clean`) on `published.provision`; the `provision_unit` and `edge` views (`contains` and `elucidates` derived from the provisions, `refers_to` computed at publish time into `link`); migration `0014_retrieval_units`; an annex's chapter with nothing nested in it now carries its own text (it was published empty); `published-schema.md`. | platform | **Done 2026-10-20.** Platform 590 tests pass (with the database tests). Over the 4,132 snapshot texts: 692,059 provisions and 174,313 `refers_to` links in 59 s, the slowest text 0.9 s. A provision whose body is only its heading line (a column-printed label whose wording the text layer put elsewhere) has no wording, and so is no unit. |
| 7 | **Connectors** (one PR each): DSN-MUI, BPK, OJK, BI as in [Where each connector plugs in](#where-each-connector-plugs-in), with `METAMORPH_PDF_ENGINE` read in each composition root. Airflow and `compose.yaml` forward the settings. Existing tests run under the `pymupdf` engine unchanged. New tests run the connector's extractor with a cached MinerU result. | four connectors, platform `dags/` | **Done 2026-10-20.** Suites: DSN-MUI 40, BPK 285, OJK 248, BI 102, platform 592. Each new test runs the connector's extraction with a fake `ExtractPdf`. The rollback is by construction: under `pymupdf` each connector calls its own extraction, unchanged, and leaves no MinerU record behind. BI's test checks the record JSON is byte for byte as before. As built, how each connector keeps the extraction until export:
  - **DSN-MUI:** `<sha>.extraction.json` beside the Latin text, with MinerU's Arabic in `<sha>.ara.txt`. Tesseract's file is untouched.
  - **BPK:** a `texts.extraction` column in its SQLite, with its own `Extraction` DTO, because its application ring doesn't import the contract. The port's `extract` takes the file's role.
  - **OJK:** in the main file's description in `content_extra_json`, only when MinerU read it.
  - **BI:** in the version's `extraction` key in `processed_json`. The database path keeps pages and hash only, since the export reads the JSON. |
| 8 | **Service:** `docker/mineru/` (dev plist, production Dockerfile, compose profile), the README section "Running MinerU", and a `scripts/mineru_check.py` that verifies the version, the tiers and the models through `/v1/health` and `/v1/tiers`. | platform | **Done 2026-10-21.** The check passes on this Mac: MinerU 4.0.12, both tiers, and each tier's models read a page from its text and from its image. A connector image on the compose network read a BI regulation through `from_environment`, and its second read came from the cache. As built:
  - **The check:** `packages/metamorph-pdf-text/scripts/mineru_check.py`, beside the package's other script. It asks the reader (`MinerUReader.version`, the new `MinerUReader.tiers()`), so it checks what the connectors will use.
  - **Dev service:** `docker/mineru/run-dev.sh` (native, `--tier standard --concurrency 1 --preload-models`, the API key from `.env`) and `dev.mineru.plist`, a launchd agent template that the README installs. A container reaches the service's `127.0.0.1:8010` as `host.docker.internal:8010`.
  - **Production:** `docker/mineru/Dockerfile` (`mineru[full]==4.0.12`, vLLM, the models in the image) and the compose service `mineru` (profile `mineru`, an NVIDIA reservation, a health check on `/v1/health`). They are written, not built here: there is no NVIDIA GPU to run them on.
  - **The measured rates** are in [Throughput](#deployment-and-dependencies). The model licenses are in the README.
  - **Fixed on the way:** MinerU marks the preamble's labels ("Mengingat", in a column of their own) as `aside_text`, which cleaning dropped as furniture. `shows_structure` now also keeps opening labels and rulings (`HEADING_LINE`). |
| 9 | **Full re-extraction into a scratch database** (the validation run, replacing a pilot; run on AWS per [aws-step9-guide.md](aws-step9-guide.md), since this Mac needs 2–3 days): each connector re-extracts every file it holds with `mineru`; bundles are exported and loaded into a scratch Postgres, then parsed with parser 6. EDA harness `Metamorph-EDA/2026-10-2x-mineru-extraction/` (snapshot → re-extract → parse → compare, as in the printed-lines study). | EDA | every criterion in [Validation](#validation) is met, or a failing case is fixed in steps 1–7 and the run repeated. The user then runs the live re-extraction and load. |
| 10 | **Reader check:** the curation web reader on a sample of each connector's texts; `domain/layout.py`'s coverage invariant holds (every kept word is in a block). | platform, web | e2e suite passes |
| 11 | **Retire the old OCR paths** once the live run has passed: `OcrTextExtractor`, BI's Tesseract call, `ocr_arabic.py`, and `ocrmypdf` and Tesseract in the images. `pymupdf` stays as the rollback engine. | connectors | images rebuild smaller; the suites pass |
| 12 | **Attribution and records:** "Text extraction by MinerU" in the curation web app's footer and in the README, as the license requires if the service is offered to third parties; the EDA report linked from the EDA index; this plan's status updated. | web, platform, EDA | done |

## Validation

These criteria are measured over the **whole corpus** in step 9, against the `pymupdf` + printed-lines baseline (EDA 2026-10-20). They replace the pilot's go/no-go: if one fails, the rollout of that connector waits.

### Fidelity: wording is not rewritten

| Check | Criterion |
|---|---|
| Born-digital pages (`ocr_mode` resolved `txt`): words missing or changed against PyMuPDF, excluding logged removals | **0** on pages kept. A failing page falls back; the fallback rate is reported per connector and must be **≤ 2%** of pages. |
| Words removed by cleaning: each removal rule's sample of 50 removals, read by hand | **0** removals of wording |
| Numbers (`\d+` tokens) per born-digital text, before and after, outside removed furniture | identical |

### Noise: what was asked to go

| Check | Criterion |
|---|---|
| `SK No …` lines left | **0** |
| Lines repeated in the top or bottom band on ≥ 30% of a document's pages | **0** outside the guard list |
| Catchwords left at page ends | **0** |
| Noisy texts (out-of-vocabulary rate > 8%, confusions > 10 per 1k tokens, or > 2 damaged headings), DSN-MUI measured on its Latin text with a fatwa vocabulary | DSN-MUI **≤ 8 of 164**; BPK **≤ 3 of 92**; OJK **≤ 1**; BI **≤ 8** (not worse) |
| Glyph junk (CJK, Greek, or private-use characters in Latin text) | **0** characters in any connector's contract text |

### OCR accuracy: a hand-checked gold set

There are 100 pages, transcribed by hand from the official PDFs and kept in `Metamorph-EDA/2026-10-2x-mineru-extraction/gold/`:
- 40 BPK pages (scans and publisher OCR);
- 30 DSN-MUI pages (Latin and Arabic);
- 15 OJK pages;
- 15 BI pages.

| Check | Criterion |
|---|---|
| Latin character error rate | **≤ 1%** per connector, and below today's text on the same pages |
| Arabic character error rate (DSN-MUI `.ara.txt`) | below today's Tesseract output on the same pages |
| Heading and marker accuracy (`Pasal N`, `(n)`, `a.`) on the gold pages | **100%** |

### Structure: every unit kept apart

| Check | Criterion |
|---|---|
| Suspect texts (structure problems) | not above the baseline of **52**, and no connector worse |
| Clean texts that become suspect | **0** unexplained (each is read and classified) |
| Pasal and ayat counts per clean text, parser 5 on baseline vs parser 6 on MinerU | identical, or the difference explained (a heading the old text lost) |
| New `huruf`/`angka` units | Present in every Ketentuan Umum and Menimbang of the gold documents. Letter and number sequences have no gaps outside quoted amendments. |
| Headings on their own line (`BAB`, `Bagian`, `Paragraf`, `Pasal`) | **100%** of parsed headings |

### Links and readiness for downstream use

| Check | Criterion |
|---|---|
| Resolved citations | not fewer than the baseline; unresolved not more |
| In-document references | linked to items where the item exists |
| `provision_unit` | every unit has a non-empty `wording` and a `heading_path` reaching its root; no unit body contains a page marker or a furniture line |
| Reader | coverage invariant holds on all texts; e2e suite passes |

### Operations

| Check | Criterion |
|---|---|
| Files processed | 100% of held PDFs, or each failure listed with its MinerU error |
| Reproducibility | a second re-extraction from the cache gives byte-identical texts |
| Rollback | `METAMORPH_PDF_ENGINE=pymupdf` re-extraction gives byte-identical texts to the baseline |
| Throughput | measured per tier and recorded in the EDA report |

## Rollback

- **Per connector, at any time:** set `METAMORPH_PDF_ENGINE=pymupdf` and run the connector's re-extract command:
  - BPK: `extract --again`
  - BI: `reextract`
  - OJK and DSN-MUI: their re-extract scripts

  Then export and load. The texts are byte-identical to today's (step 3's test). `printed_text` and `METAMORPH_PDF_LINES` keep working beneath it.
- **Parser 6:** reverting `PARSER_VERSION` to `"5"` re-parses every text with the old grammar. The new provision kinds disappear with that parse, and `published` rebuilds from it.
- **Schema:** the platform's migrations only go forward. Migration 0013 adds two nullable `extraction` columns that nothing else depends on. A rollback leaves them `NULL`, and contract 2.0 bundles keep loading. Parser 6's view (step 6) is additive in the same way.
- **Nothing irreversible:**
  - Old text versions stay in `registry.text_version` (`is_current=false`).
  - MinerU's results stay in the cache.
  - No source file is changed.

## Risks and open questions

| Risk | Mitigation |
|---|---|
| The VLM rewrites or drops wording on born-digital pages | Page-level word alignment against PyMuPDF with fallback (pipeline step 4); the fidelity criteria |
| Furniture rules remove real text | Position plus repetition, heading guards, the removal log and a hand-read sample per rule |
| Arabic quality is unknown | Gold pages and a criterion against today's Tesseract output. If it fails, DSN-MUI keeps `ocr_arabic.py` for the side file while MinerU still reads the Latin. |
| MinerU changes fast (8 releases in 3 weeks; breaking CLI changes) | Exact pin; the version in every text's provenance; the cache keyed by version; the adapter is the only code touching its JSON |
| Throughput on this Mac | `basic` for non-main files; resumable runs through the cache; production on a GPU host |
| Model weight licenses | **Checked 2026-10-21:** `opendatalab/MinerU-4_models_torch` and `opendatalab/MinerU2.5-Pro-2605-1.2B`, which production runs, are Apache 2.0. The Mac's VLM is `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`, a third party's conversion whose card states no license, so it is used for development only. Recorded in the README. |
| The VLM drops list markers on born-digital pages | Seen in step 8: on PADG 19/2024 the standard tier lost "c." and "1.", and both pages fell back to the text layer, as the wording check is meant to do. Step 9 measures how often pages fall back, by connector and tier. |
| Text-layer artifacts make good pages fall back | The same PDF's text layer has an invisible "2" at the top of page 1, which MinerU rightly omits, and that alone sends the page back to the layer. The output is no worse than today's; step 9 counts such cases before any rule is loosened. |
| No pilot: the first run is the evidence | Step 9 runs into a scratch database, and live data is touched only after every criterion passes |
| MinerU service down during an ingest | Tasks fail and retry (principle 4); Airflow's retries; no half-switched texts |

## Critical files

- **New:** `packages/metamorph-pdf-text/` (domain, application, adapters, tests), `docker/mineru/`, the EDA study folder
- **Platform:**
  - `domain/structure/{grammars,model,quality}.py`, `domain/cross_references.py`, `domain/reading.py`
  - the published views and migrations
  - `docs/published-schema.md`, `packages/metamorph-contract/` (schema, `CONTRACT_V2.md`)
  - `dags/metamorph_pipeline/jobs.py`, `compose.yaml`, `.env.example`
- **BPK:** `adapters/extraction/mineru.py` (new), `wiring.py`, `Dockerfile`
- **BI:** `src/pipeline/extractor.py`, `src/config.py`, `src/pipeline/reextract.py`
- **OJK:** `src/ojk_connector/pdf_text.py`, `sources/jdih/source.py`
- **DSN-MUI:** `dsn_ingest/extract.py`, `scripts/ocr_arabic.py`, `scripts/reextract.py`
