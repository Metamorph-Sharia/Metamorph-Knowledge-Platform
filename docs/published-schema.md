# The `published` schema: the read contract

The Knowledge and Retrieval layer reads **only** the `published` schema. It never reads `registry`, `curation` or `ingest`. Everything here is already resolved:
- values are effective: what the sources say, with the Metamorph team's corrections applied;
- suppressed documents are gone;
- only `public` or `licensed` content appears. RegAlert's English translations and BPK's abstracts never do;
- only documents that pass the platform's checks appear: a canonical ID, a main text the current parser read, and a structure with no problems (or one a curator approved as it is). A document that later fails keeps its last published version until it passes again.

Each document's rows are rewritten together whenever anything about it changes.

## Indexing incrementally

`published.change_log` records every write: `added`, `updated` or `removed`, with `changed_at`. To keep an index current, remember the last `changed_at` you processed. Then re-read the documents logged after it, and drop the ones logged as `removed`.

```sql
SELECT DISTINCT ON (document_id) document_id, change
FROM published.change_log WHERE changed_at > :last_seen
ORDER BY document_id, changed_at DESC;
```

## Tables

| Table | One row per | Key columns |
|---|---|---|
| `document` | document | `id`, `issuer`, `family`, `number`, `year`, `citation`, `title`, `kind`, `status`, `enacted_on`, `promulgated_on`, `effective_on`, `aliases[]`, `curated` |
| `document_source` | source record describing it | `connector`, `source_id`, `url`, `fetched_at` |
| `file` | official file (PDF, HTML page …) | `sha256`, `role` (main, annex, faq, guide, abstract, other …), `media_type`, `storage_key` |
| `text` | text of the document | `sha256`, `language`, `origin`, `method` (text_layer, ocr, source), `paged`, `of_file`, `storage_key`, `extraction` (how an engine read it: `engine`, `engine_version`, `tier`, `ocr_mode`, `pages_ocrd`, `pages_fallen_back`; null when the connector read it itself) |
| `provision` | addressable unit of a text | `text_sha256`, `address`, `parent_address`, `kind`, `label`, `heading`, `ordinal`, `body`, `char_start`/`char_end`, `page_start`/`page_end`, `valid_to`, `search` (the body's `tsvector`, `simple` configuration, GIN-indexed), `heading_path` (each provision from the root down to this one: `{"BAB II KEGIATAN USAHA", "Pasal 5", "(1)"}`), `depth` (how many provisions hold it), `wording` (the body without its own heading lines and page furniture: what to read or embed) |
| `link` | relation from this document to another | `type`, `from_address`, `to_document`, `to_address`, `effective_on`, `confidence` |
| `provision_unit` (view) | **what to embed**: the smallest provisions with wording of their own | `document_id`, `address`, `kind`, `label`, `heading`, `heading_path`, `wording`, `text_sha256`, `page_start`/`page_end`, `valid_from`/`valid_to`; the document's `issuer`, `family`, `number`, `year`, `citation`, `title`, `status`, `effective_on`; `elucidation_address` (its `penjelasan/…`, if published); `under_review` (a review note is on it or on a provision holding it) |
| `edge` (view) | **the graph**: every link and the structure, in one place | `type`, `from_document`, `from_address`, `to_document`, `to_address`, `effective_on`, `confidence` |
| `review` | structure warning to review | `ordinal` (the text's reading order), `address` (the provision it names; null: the document), `note` ("pasal-4: ayat (2) missing", "Pasal 9 missing") |
| `status_event` | status change in the document's history | `address` (null: the whole document), `status`, `effective_from`, `source` |
| `change_log` | write to the schema | `document_id`, `change`, `changed_at` |

## Identifiers

`document.id` is a canonical ID named after the issuer, whichever source found the document:

| Issuer | Pattern | Example |
|---|---|---|
| OJK | `ojk:{pojk\|seojk\|padk}:{year}:{n}` | `ojk:pojk:2019:10` |
| Bank Indonesia | `bi:{pbi\|padg\|sebi}:{year}:{n}` | `bi:pbi:2021:6` |
| DSN-MUI | `dsnmui:fatwa:{n}` | `dsnmui:fatwa:117` |
| National (via BPK) | `id:{uu\|perppu\|pp\|perpres\|pmk\|…}:{year}:{n}` | `id:uu:2011:21` |
| Not yet identified | `unresolved:{connector}:{key}` | treat it as provisional; a curator assigns the real ID |

## Texts and provisions

- **Text bytes** are in the object store under `storage_key`. Paged texts mark pages with `<!-- page N -->` lines.
- **Provisions are cut from those texts.** `body = text[char_start:char_end]`, with page numbers when the text is paged. Headings that only group others (`bab`, `bagian`, `paragraf`, the `penjelasan` root, an annex with chapters) have an empty `body`, because their children carry the text.
- **Addresses** are stable within a text:

| Address | Meaning |
|---|---|
| `menimbang`, `mengingat` | The considerations and the legal basis |
| `bab-ii`, `bab-ii/bagian-kesatu` | A chapter and its part |
| `pasal-5`, `pasal-5/ayat-1` | An article and its paragraph: the unit lawyers cite |
| `pasal-5/ayat-1/huruf-a`, `pasal-1/angka-3`, `pasal-1/angka-3/huruf-b` | An item of a paragraph or an article (`huruf` lettered, `angka` numbered), and an item within an item. The preamble's, a circular section's and a ruling's items too: `menimbang/huruf-a`, `mengingat/angka-2`, `romawi-ii/angka-3`, `diktum-kedua/angka-1`. |
| `penjelasan/pasal-5/ayat-1/huruf-a` | The elucidation of that item (`kind` `penjelasan`, label `Huruf a`) |
| `pasal-i/pasal-115` | Article 115 as worded by an amending regulation's Pasal I |
| `penjelasan/pasal-5`, `penjelasan/pasal-5/ayat-1` | The official elucidation of that article or paragraph |
| `lampiran-i`, `lampiran-i/bab-ii` | An annex and its chapters |
| `romawi-ii` | A circular's (SEOJK, SEBI) Roman-numbered section |
| `diktum-kedua` | A fatwa's second ruling |

- A text can have several provision trees: BI sometimes publishes a regulation's body and its elucidation as separate PDFs. Group provisions by `text_sha256`.
- Some texts' structure failed the platform's quality checks: a gap in the article numbers, or missing paragraphs. They are still published, with each gap in `review` until the Metamorph team corrects the text or approves the gap as genuine. A regulation with no articles at all (a captured web page instead of the regulation) is held back.

## Retrieval units and the graph

**A unit** (`provision_unit`) is the smallest provision with wording of its own:
- an ayat, with its items;
- a pasal without ayat;
- a fatwa's ruling, or a circular's section without a provision of its own inside;
- the preamble's parts;
- an elucidation entry.

A grouping heading (`bab`, `bagian`, `paragraf`) and an article whose ayat carry its wording are context, not units. A unit's items (`huruf`, `angka`) stay addressable in `provision`, so a long unit, such as a Ketentuan Umum's definitions, can be split by them.

**Embedding input.** We recommend `"{citation}, {heading_path joined by ' › '}\n{wording}"`, e.g. `POJK 10/POJK.05/2019, BAB II KEGIATAN USAHA › Pasal 5 › (1)` followed by the words. Re-embed a document when `change_log` says it changed.

**Units under review.** A gap in a text's numbering, such as an article or ayat missing, or an elucidation of an article the body lacks, doesn't hold the document back. It is published, and the gap is a note in `review`, so retrieval can still use the text. The gap costs a unit's boundary, not its words: a lost heading's wording usually runs on in the unit before it. `under_review` marks the units a note is on. Only a regulation with no article found is held, since it has no provision to retrieve or cite.

**Edges** (`edge`) are `link`'s rows plus three kinds of edge between one document's own provisions:

| `type` | From → to | Comes from |
|---|---|---|
| `contains` | a provision → each provision directly inside it | `parent_address` |
| `elucidates` | `penjelasan/X` → `X` | the addresses |
| `refers_to` | a provision → another provision it names ("sebagaimana dimaksud dalam Pasal 5 ayat (1) huruf a") | its wording, read when the document is published. It is credited to the innermost provision holding the reference, and stored in `link`. |

`refers_to` also links one fatwa to another fatwa it cites. That edge is between documents, so `to_document` differs from `from_document`.

## Links

`link.type` uses the contract's vocabulary:

| Type | Meaning |
|---|---|
| `legal_basis` | Named in "Mengingat" |
| `implements` | Carries out an article of another instrument (`to_address` names the article) |
| `amends`, `supersedes` | Changes, or replaces, another instrument |
| `revokes`, `partly_revokes` | Revokes another instrument, or some of its articles |
| `adopts_fatwa` | A regulation relies on a DSN-MUI fatwa |
| `changes_fatwa` | A ta'limat changes a fatwa |
| `refers_to` | Any other reference |

A link may point to a document that isn't published. Join on `document.id` when you need the target. Links come from source metadata, such as RegAlert's or BPK's lineage, or from the document's own text (Mengingat, closing provisions, amending instructions).

## Status and validity

- `document.status` is one of `in_force`, `amended`, `partly_revoked`, `revoked`, `not_yet_in_force` or `unknown`. A source's status wins. When the source has none (BI, DSN-MUI), the status comes from the latest `status_event` that another document's link implies.
- `status_event` holds the history. `source = 'links'` marks events derived from amending or revoking links. They are dated from the changing document's effective date, and an event with an `address` is about one article.
- `provision.valid_to` is set on an article, and everything under it, once a later instrument amends or revokes that article. It is the date the original wording stopped applying. The new wording lives in the amending document, under `pasal-i/pasal-N`.

## What is derived rather than stated by a source

- **Dates:** when a source sends none (OJK, BI), `enacted_on`, `promulgated_on` and `effective_on` come from the document's own closing text ("Ditetapkan … pada tanggal …", "mulai berlaku pada tanggal diundangkan").
- **Status:** see above.
- **Provisions and text-derived links:** these come from the shared structure parser. Its version is recorded in the registry, and everything is re-derived when it changes.
- **Arabic text:** DSN-MUI fatwas carry a separate Arabic text (`language = 'ar'`, `method = 'ocr'`), about 85% accurate. It is good for retrieval, but don't quote it as the authoritative wording.
