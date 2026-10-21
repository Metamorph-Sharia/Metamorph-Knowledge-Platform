# metamorph-pdf-text

Turns an official file's pages into the plain text a connector exports: page furniture removed, every heading and
list item on a line of its own, so the platform's parser can cut *Bab*, *Bagian*, *Paragraf*, *Pasal*, *Ayat* and
each item apart. The plan: [docs/mineru-extraction-plan.md](../../docs/mineru-extraction-plan.md).

## Using it in a connector

```python
import os
from metamorph_contract import join_pages
from metamorph_pdf_text import from_environment, wants_mineru

if wants_mineru(os.environ):  # METAMORPH_PDF_ENGINE=mineru
    extract = from_environment(os.environ)  # built once, in the composition root
    extracted = extract.run(pdf_bytes, role="main")
    text = join_pages(list(extracted.pages))
    extracted.method, extracted.extraction  # → the contract's TextRef
else:
    ...  # the connector's own extraction, unchanged: the rollback
```

| Setting | |
|---|---|
| `METAMORPH_PDF_ENGINE` | `pymupdf` (default) or `mineru` |
| `METAMORPH_MINERU_URL` | the MinerU 4.0.12 service (`mineru-kit api-server`), e.g. `http://host.docker.internal:8010` |
| `METAMORPH_MINERU_API_KEY` | its key, if it was started with `--api-key` |
| `METAMORPH_MINERU_CACHE` | a directory: what MinerU read is kept there and never read twice alike |

`ExtractionUnavailable` means retry the task later (the service is down or busy). `ExtractionFailed` means this
file can't be read. Nothing falls back between engines.

## The rings

Each ring imports only the rings inside it (`tests/test_architecture.py`). The domain and application use the
standard library only.

| Module | What it does |
|---|---|
| `domain/page.py` | `Page`, `Block`, `BlockKind`, `BBox`: a page as a reader laid it out, in reading order |
| `domain/cleaning.py` | `clean(pages)`: furniture the reader marked, the `SK No …` print serial however misread, printed page numbers that follow the pages, running heads (their first place stays), catchwords, hyphenation, whitespace. Each removal is logged. |
| `domain/rendering.py` | `render(pages)`: one plain-text string a page, laid out for the parser |
| `domain/alignment.py` | `aligned(candidate, reference)`: the words one reading has that the other lacks |
| `domain/quality.py` | `page_quality(text, vocabulary)`: unknown words, OCR confusions, damaged headings, glyph junk |
| `application/extract_pdf.py` | `ExtractPdf.run(pdf, role)`: reads the text layer, plans the request, reads (or takes from the cache), cleans and renders both readings. A page keeps the layout reader's text only where it can be trusted; otherwise it falls back to the text layer, counted in `Extraction`. |
| `application/policy.py` | `request_for(role, quality)`: `standard` for the regulation, `basic` for the rest; OCR is forced when more than a fifth of the text layer is noisy |
| `application/ports.py`, `reading.py` | `LayoutReader`, `ResultCache`, `CacheKey`; `ReadRequest`, `Reading`, `Tier`, `OcrMode`; `ExtractionUnavailable`, `ExtractionFailed` |
| `adapters/mineru_reader.py` | The V1 API client: upload (by sha256), parse job, poll, Middle JSON. Pinned to MinerU 4.0.12. |
| `adapters/mineru_layout.py` | Middle JSON (`docvortex.middle` 2.0) → pages of blocks. This is the only code that knows its shape. |
| `adapters/pymupdf_reader.py` | The PDF's text layer, printed lines joined per block: the reference |
| `adapters/file_cache.py` | Readings as JSON files, by file, engine, version and request |
| `adapters/vocabulary.txt` | 13,553 words of clean texts, built by `scripts/build_vocabulary.py` |
| `environment.py` | The composition root: `wants_mineru`, `from_environment`, `SETTINGS` |

Cleaning removes; it never rewrites a word. The only joins are a word hyphenated across two lines and whitespace.
