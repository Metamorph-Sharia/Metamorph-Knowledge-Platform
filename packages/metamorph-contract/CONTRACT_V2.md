# Contract v2: the normalized document

**Version 2.1 · 2026-10-20** (2.0 · 2026-10-14) · package `metamorph-contract` (Python ≥ 3.11; depends on `jsonschema`)

**2.1 adds one optional field**, `texts[].extraction`: how an engine read the text from its file. A 2.0 document or bundle reads as it did. A connector writes 2.1 (`CONTRACT_VERSION`), and the platform reads both (`READABLE_VERSIONS`).

**The formal contract is two JSON Schemas (draft 2020-12):**

| Schema | Describes |
|---|---|
| [`normalized-document.schema.json`](src/metamorph_contract/schemas/normalized-document.schema.json) (`urn:metamorph:contract:2.1:normalized-document`) | One line of `documents.jsonl` |
| [`bundle-manifest.schema.json`](src/metamorph_contract/schemas/bundle-manifest.schema.json) (`urn:metamorph:contract:2.0:bundle-manifest`) | `manifest.json` |

Any system, in any language, can validate against them. The Python package mirrors them exactly (a test fails on any drift), and adds the rules a schema can't express (see [The document](#the-document)).

Interface v1.0 (`discover`, `fetch`) moves a source's raw files. Contract v2 adds the shared shape of **what a document is**: identity, status, files, texts, provisions and citations. Every connector exports it, and one platform loader reads it into PostgreSQL. v1.0 is unchanged and still applies.

**What you write:** an `export --format v2` command that turns what your connector holds into a bundle.
**What you don't write:** database code, link resolution, structure parsing, or anything about other sources. The platform does those the same way for every connector.

## The rules

1. **One owner per issuer.** Each connector exports only documents its issuer published: OJK → `ojk:`, BI → `bi:`, DSN-MUI → `dsnmui:`, BPK → `id:` (national laws and ministerial rules).
2. **Canonical IDs come from the document's own number, never from a URL.** Use `canonical_id()`. If you can't tell, use `unresolved_id(connector, source_id)` with `id_confidence` `none` or `conflict`. The document still loads, and a person resolves it.
3. **Pointers, not payloads.** Files and texts are blobs in the bundle, referenced by sha256 (`put_blob`, `put_text`).
4. **Paged texts use `<!-- page N -->` markers** (`join_pages`), so a citation can point to a page of the official PDF.
5. **Restricted content never enters a bundle.** Bundle only `public` or `licensed` rights. The validator rejects `restricted`.
6. **Report citations; don't resolve them.** Write what the document cites, with `target_id` when you can parse it. The platform links it, possibly after another connector has loaded the target.
7. **Pass the source's own fields through unchanged** in `source_fields`, beside your interpretation, never instead of it.
8. **A bundle is a full snapshot.** Every document you hold goes in each export. A document missing from a complete bundle means "gone from the source".

## Canonical IDs

`{issuer}:{family}[:{year}]:{number}`, lowercase. Omit the year only when numbers never repeat across years.

| Issuer | Families | Examples |
|---|---|---|
| `ojk` | `pojk`, `seojk`, `padk` | `ojk:pojk:2014:5`, `ojk:padk:2026:11` |
| `bi` | `pbi`, `padg`, `sebi` | `bi:pbi:2026:8`, `bi:padg:2026:31` |
| `dsnmui` | `fatwa`, `pedoman`, `talimat` | `dsnmui:fatwa:117` (fatwa numbers run continuously) |
| `id` | `uu`, `perppu`, `pp`, `perpres`, `pmk`, `permenkum`, … | `id:uu:2011:21`, `id:pmk:2017:23` |

Put every other way people cite the document in `aliases` (`5/POJK.05/2014`, `POJK 5/2014`). The platform resolves citations through them.

## The document

```text
NormalizedDocument
  contract_version   "2.0"
  source             SourceRef: connector, connector_version, source_id, url, fetched_at (ISO datetime with timezone)
  document           DocumentInfo:
                       id, id_confidence (high|medium|low|conflict|none), id_evidence
                       issuer, family, number, year, citation, title, language, aliases
                       kind     law | regulation | implementing_rule | fatwa | guideline | circular | explanatory
                       status   StatusClaim: value (in_force|amended|partly_revoked|revoked|not_yet_in_force|unknown),
                                source (who says so), as_of
                       dates    enacted, promulgated, effective (ISO dates)
  files[]            FileRef: sha256, role (main|annex|abstract|faq|guide|page_html|api_payload|other),
                       media_type, source_url, rights, title, pages
  texts[]            TextRef: sha256, language, origin (self_extracted|source_text|source_translation),
                       method (text_layer|ocr|source), rights, paged, of_file,
                       extraction (2.1, or null): engine, engine_version, tier, ocr_mode (txt|ocr), pages_ocrd,
                       pages_fallen_back
  provisions[]       optional: address ("pasal-115/ayat-1"), kind, label, text (sha), char_start, char_end,
                       parent, heading, page_start, page_end
  citations[]        relation (amends|revokes|partly_revokes|supersedes|implements|legal_basis|
                       adopts_fatwa|changes_fatwa|refers_to), target_text, evidence,
                       found_in (text|source_metadata), confidence, target_id, from_address, to_address
  source_fields      the source's own fields, unchanged
```

A document must carry content: at least one file or one text. A text supplied by a source, before the official file has been fetched, is enough.

The JSON Schema defines every field, vocabulary, pattern and format (`date`, `date-time` with time zone). `document.py` mirrors it as Python types. `validate.py` adds the rules that compare one value with another:
- an unresolved ID needs confidence `none` or `conflict`, and a canonical one must not have them;
- the ID's issuer must equal `issuer`;
- no file or text is listed twice;
- `of_file` and each provision's `text` and `parent` must point inside the same document;
- `char_start ≤ char_end`.

`problems(document)` runs both the schema and these rules, and returns every problem at once.

## Writing a bundle

```python
from metamorph_contract import BundleWriter, canonical_id, join_pages, ...

with BundleWriter(out_dir, connector="ojk", connector_version="0.4.0", run_id=run_id) as bundle:
    for held in my_documents():
        pdf_sha = bundle.put_blob(held.pdf_bytes)
        text_sha = bundle.put_text(join_pages(held.pages))
        bundle.add(NormalizedDocument(...))      # validated here: ContractViolation lists every problem
# the manifest is written only on a clean exit
```

```text
{bundle}/manifest.json           connector, connector_version, run_id, created_at, counts, complete, contract_version
{bundle}/documents.jsonl         one document per line
{bundle}/blobs/{sha[:2]}/{sha}   every file and text referenced
```

A bundle without a manifest, or whose manifest breaks its schema (wrong contract version, `complete` not `true`), raises `UnloadableBundle` and is never loaded. So a crashed export can't make documents look deleted.

## Text from a PDF

Read each page a printed line to a line: `printed_text(page.get_text(), page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT))`. PyMuPDF's own lines split a justified line that the PDF sets word by word ("selanjutnya / disebut / Pengolahan / adalah") and put a list's number on a line apart from its text ("16. / Pengolahan …"). `printed_text` joins the lines that share a baseline in one block, left to right, and changes nothing else: the characters, their order and every other line break stay PyMuPDF's. A page whose layout doesn't hold its text's lines is left as PyMuPDF reads it.

`METAMORPH_PDF_LINES=extracted` keeps PyMuPDF's own lines, as before: every connector reads it (`wants_printed_lines(os.environ)`), so one setting rolls the change back. Re-extract the files you hold to apply either way to texts already exported.

## How a text was read (2.1)

A text an engine read (MinerU, through `metamorph-pdf-text`) carries `extraction`:

| Field | |
|---|---|
| `engine`, `engine_version` | e.g. `mineru`, `4.0.12+t1`: the engine's exact version, and the translation's revision. Another version reads a file differently. |
| `tier` | the engine's quality tier, e.g. `basic` or `standard` |
| `ocr_mode` | how the engine read the file: `txt` (its characters) or `ocr` (its page images) |
| `pages_ocrd` | pages kept as the engine's OCR. `method` is `ocr` when there is at least one. |
| `pages_fallen_back` | pages the engine's reading couldn't be trusted on, kept as the file's own text layer |

A text read by a connector's own PDF reading has `extraction: null`, as every text did before 2.1.

**Such a text is laid out for the parser:**
- one paragraph per line, with a blank line between blocks;
- each heading on a line of its own (`BAB IV` and its title, `Bagian Kesatu`, `Paragraf 2`, `Pasal 5`, `Menimbang :`, `MEMUTUSKAN:`, a fatwa's `Kedua :`);
- each item opening a line (`(1)`, `a.`, `1.`, `IV.`);
- a table one row a line, cells separated by ` | `.

Page furniture is removed: headers, footers and page numbers, the `SK No …` print serial, running heads, and catchwords. No word is rewritten.

## Checklist

- [ ] `export --format v2 --out DIR` writes one bundle per run, containing every document held.
- [ ] IDs come from `canonical_id()` or `unresolved_id()`; aliases list the other citation forms.
- [ ] The official files are in `files` once you hold them; texts are paged with `join_pages` where pages are known.
- [ ] A PDF's text is read with `printed_text`, unless `wants_printed_lines(os.environ)` says otherwise.
- [ ] With `METAMORPH_PDF_ENGINE=mineru` (`metamorph_pdf_text.wants_mineru`), a PDF's text is read with `metamorph_pdf_text.from_environment(os.environ)`, and its `extraction` is written.
- [ ] No `restricted` file or text is bundled.
- [ ] Citations found in source metadata are exported, with `target_id` where it can be parsed.
- [ ] A test exports fixtures and asserts that every `Bundle(dir).entries()` entry `is_valid`.
