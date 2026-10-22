# Engineering principles

These hold for the platform, the connectors and `packages/metamorph-pdf-text`. They were set by the project owner on 2026-10-22, after step 9 of the MinerU rollout. The rollout had grown a rule for each defect found, and several of those rules broke other documents.

## Clean enough for retrieval, not a perfect conversion

The goal is text clean enough for vector retrieval and for quoting in answers. It is not a faithful conversion of every page. **Build the simplest pipeline that keeps the legal information clean enough.**

Extraction quality is prioritised by its impact on retrieval and answer accuracy:
- **Most:** the body of a regulation. Its articles, paragraphs, items and elucidation, with their markers ("(3)", "b.") and legal references ("Pasal 62", "ayat (1)", "Nomor 7 Tahun 2011"), since one of them lost can change what a provision says. Tables in the body count.
- **Less:** appendix (lampiran) tables, forms and other material that is rarely retrieved.
- **Least:** typography: spacing, quote shapes, a stray mark that changes no word.

## General solutions only

- **Fix a problem only when it is meaningful across documents.** It must lose or corrupt legal content in many documents, or in a whole class of them. A quirk of one regulation is recorded, not fixed.
- **No document-specific rules.** A rule must never name a regulation, an issuer's one-off layout, or a word list tuned until one document passes. Rules work from layout (a block's kind and position, a line repeated across pages) and from general language (hyphenation, reduplication), not from exceptions.
- **Each owner keeps its own knowledge.** Extraction knows layout. The parser is the one owner of legal structure (BAB, Pasal, ayat, items). A structure problem is fixed in the parser's grammar, not by re-shaping text in extraction.
- **Count the cost of a rule.** Every rule adds code, tests and a chance to break another document, and new kinds of document are coming. A rule is added only when its benefit, measured across the corpus, outweighs that. A rule that causes regressions elsewhere is removed, not patched with exceptions.
- **Prefer removing complexity to adding it.** When two rules overlap, or a rule only serves a case another mechanism already covers, remove one.

## Checks warn; fallbacks need strong evidence

- A failed check need not change the output. Fall back to another reading only on strong evidence that a reading is unreliable: a born-digital page's words differ from the PDF's own characters, or OCR is noisier than the text layer.
- Weaker signs **warn and keep the reading**. A gap in a text's numbering ("Pasal 3 missing", "pasal-4: ayat (2) missing") publishes the document and notes the gap in `published.review`, on the unit it names (`provision_unit.under_review`).
- **Hold back or exclude content only on evidence of material corruption** that would compromise legal meaning or retrieval: today, a regulation with no article found.
- A warning comes from one general check, the parser's numbering, which works the same for every reading of every document. A page-level marker check against the PDF's text layer was tried and dropped (2026-10-22): on scans the layer is the publisher's own OCR, and most of its flags were that layer's misreadings.

## Validate by impact

- A rollout waits on **a few gates** tied to retrieval:
  - the PDF's own words are kept;
  - OCR is good enough on prose;
  - retrieval units are intact;
  - retrieval units carry no page noise;
  - operations: every file processed, reproducible, rollback exact.
- Everything else is **monitored and reported**, never blocking on its own. See Validation in [mineru-extraction-plan.md](mineru-extraction-plan.md).
- Regressions are sampled and triaged by their effect on retrieval, not chased to zero one by one.
