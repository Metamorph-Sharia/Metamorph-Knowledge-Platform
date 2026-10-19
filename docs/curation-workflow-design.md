# Design: curation workflow with a publish gate

**Status:** Release 1 (the gate) built and rolled out, 2026-10-19. Release 2 (text correction) built, 2026-10-19; its migration (0011) not yet applied to the live database
**Scope:** the curation app, the publish step, and the parse step's input. Connectors and contract v2 are unchanged.
**Implementation plan:** [curation-workflow-implementation-plan.md](curation-workflow-implementation-plan.md)

## Summary

Today every document is published, whatever its quality. The review queue records problems, but nothing it records changes what is published.

This design replaces that with one rule, one list and three actions:

- **One rule.** A document is published only when it passes the platform's checks, or a curator has approved it as it is. A document that fails is **held**. If an earlier version passed, that version stays published.
- **One list.** The held documents, each with the reasons it is held. The list is computed fresh on every build, so nothing has to be opened, closed or settled.
- **Three actions.**
  - **Correct:** a field, the ID, or now the text itself.
  - **Approve as is:** accept a remaining problem, with a reason.
  - **Suppress:** keep a document out on purpose.

Systematic problems are still fixed upstream, in the connector or the parser. The held list is where they become visible.

## Why change

Measured on 2026-10-19:

| Problem | Evidence |
|---|---|
| Publishing ignores quality | 2,592 documents are registered and **2,592 are published**. That includes 69 whose structure check fails, 24 BI documents whose regulation text was never acquired (only their FAQ, abstract or guide), and 3 with placeholder IDs. |
| A decision changes nothing | Resolving or dismissing a `structure_suspect` item leaves the broken structure published. The decision is also lost at the next re-parse. |
| The queue is organised around problems, not documents | A structure item belongs to one text version and one list of problems. Re-parsing reopens or duplicates items, and the queue needed an auto-settle step to stay accurate. |
| There is no way to fix content | Curators can correct metadata fields and IDs, but not text. Adding a document by hand refuses an ID the registry already holds. |

## Decisions

| # | Decision | Made by |
|---|---|---|
| D1 | A document that starts failing keeps its **last good version** published | User, 2026-10-19 |
| D2 | **No second-curator approval.** One curator's correction takes effect once it passes the checks | User, 2026-10-19 |
| D3 | **No label on corrected text.** The published text carries no marker that a curator edited it | User, 2026-10-19 |
| D4 | One mechanism for correcting content: **editing the text**, re-parsed at once. There is no separate structure editor | Design discussion |
| D5 | Unlinked citations and field conflicts **don't hold a document**. They are enrichment questions, not content correctness | Design discussion |
| D6 | Curation stays an **overlay**: source records and source texts are never edited | Existing architecture |

## The workflow

```
          connectors ──load──▶ registry ──parse──▶ checks
                                                     │
                       ┌────────── pass ─────────────┤
                       ▼                             ▼ fail
                   published                        held ──▶ curator: correct · approve as is · suppress
                       ▲                             │
                       └───── pass after the fix ────┘
                         (a fix can also come from a connector or the parser)
```

A curator's day:

1. Open **Held documents**. Each row shows the document, why it's held, and whether an earlier version is published ("last good version from 2026-10-12", or "never published"). Documents with a published version are listed first, because what is published for them is falling behind.
2. Open a document and fix it with whichever action fits:

   | Why it's held | Usual action |
   |---|---|
   | Structure problem: the text has the article, but the heading is damaged ("Pasa1 3") | **Edit text** and fix the heading |
   | Structure problem: the article's words are missing from the text | **Edit text** and type them in from the official PDF; the reason says which page |
   | Structure problem: the gap is real (the article was deleted, or the source skips it) | **Approve as is**, with the reason |
   | No main text (only an FAQ or abstract was acquired) | Raise it with the connector's owner; the document stays held until the connector delivers the text |
   | Placeholder ID | **Assign ID** (exists today) |
   | Too broken to fix now | **Suppress** (exists today) |

3. After **Edit text**, **Approve as is** or **Assign ID**, the platform re-parses and re-checks at once (each takes a second or two) and publishes if the document passes. The page then shows the result: *Published* or *Held: …*.

When many held documents share a reason, it's an engineering problem, not curation work. Filtering the list by reason shows these patterns; today, for example, 24 BI documents are held with no main text.

## The publish gate

### Checks

A document passes when every check passes. Each check is computed from registry and curation data on every publish.

| Check | Fails when | Hold reason shown |
|---|---|---|
| Identified | The ID is a placeholder (`unresolved:…`) | "No canonical ID yet" |
| Has its text | The document has no main text, i.e. no Indonesian text of its main file, or one that has no file | "No main text: only {roles} were acquired" |
| Parsed | A main text wasn't parsed by today's parser, from its effective content (see below) | "Not parsed with parser {N} yet" |
| Structure | A main text has structure problems, and no active approval covers exactly that text and those problems | "Pasal 3 missing; …", using the first problems as the queue shows them today |

Not part of the gate:
- Unlinked citations (D5).
- Field conflicts (D5): the curator's correction stays in effect until someone decides the conflict, as it does today.
- Rights: non-public files are already left out one file at a time.
- Arabic texts: they aren't parsed.

### What publishing does

The publish step evaluates each document it would refresh, in this order:

1. **Removed** when a curator suppressed it, or no source record points to it any more. These rules exist today and are unchanged: a curator's intent beats the gate.
2. **Held** when a check fails:
   - If a version is published, it is **left exactly as it is** (D1). Nothing is written, and the change log gets no entry.
   - If no version is published, it stays unpublished.
3. **Published** otherwise, exactly as today.

This keeps a simple invariant: **`published` only contains versions that passed the gate when they were written.** "Last known good version" therefore needs no version history. It is simply whatever `published` holds.

A held document is evaluated again on every publish, so it is published as soon as a fix lands, whether from a curator, a connector reload or a parser release.

The publish report gains a `held` count, alongside `added`, `updated` and `removed`.

## Correcting a document

### Unchanged

These work as today:
- correcting fields, and withdrawing a field correction;
- resolving field conflicts;
- assigning an ID;
- suppressing and restoring;
- adding a document no connector holds.

The published `document.curated` flag keeps its current meaning: a curator corrected a field. A text correction doesn't set it (D3).

### Approve as is

- **Where:** the Structure section of a held document, which lists the problems. The curator gives a reason, such as "Pasal 3 was deleted by POJK 12/2021".
- **Stored:** a `curation.approval` row holding the effective text's sha256, the exact list of problems, the curator, the reason and the time.
- **Valid while** that text is still the effective text and its problems are still exactly the approved ones. A new source text, a text correction or a parser change that alters the problems makes the approval lapse, and the document is held again with "the approved problems changed". This is intentional: a different text deserves a fresh look.
- **Withdrawable**, like a field correction.

### Edit text

- **Where:** an **Edit text** page for each main text of a held or published document. It has a plain text area, pre-filled with the current effective text, and a required reason that says where the corrected wording comes from (for example "PDF page 14"). Texts are 14 KB at the median and 1.8 MB at most, which a plain text area handles.
- **Checked before it's saved** (domain rule; an error is shown beside the field):
  - The text isn't empty, and differs from the current effective text.
  - For a paged text, the `<!-- page N -->` markers (the contract's paged-text convention) are unchanged and in the same order, so page numbers stay right.
  - Line endings are normalised, and the text ends with a newline, as connector texts do.
- **Stored:**
  - The corrected text goes into the blob store, which is content-addressed like every other text.
  - A `curation.text_correction` row records the source text it corrects (`corrects_sha256`), the corrected text's `sha256` and `storage_key`, the curator, the reason and the time.
  - A document has one active correction per source text. Editing again replaces it, and the editor always starts from the effective text, so successive edits build on each other.
  - The old row is kept inactive as history.
- **Effective text:** the active correction of a current text, if there is one; otherwise the source text. The rule mirrors effective field values:
  - **Parsing** reads the effective text. Provisions, citations and stated dates come from the corrected wording. `registry.text_version.parsed_sha256` records which content was parsed, so a correction or a withdrawal triggers a re-parse.
  - **Publishing** publishes the effective text: the corrected `sha256` and `storage_key`, with the source text's `language`, `origin`, `method`, `paged` and `of_file`. There is no marker (D3). Provision offsets match, because they were parsed from the same content.
- **Immediate:** the request saves, parses the changed text, re-checks and publishes. The web app already publishes after every curation change; it now parses first, which is cheap because only changed texts are parsed. The document page then shows the new state, the remaining problems if any, and a diff between the source text and the correction.
- **When the source sends a new text,** the correction no longer applies, because it corrects a text that isn't current any more. The new text is checked as it comes:
  - If it passes, it is published.
  - If it fails, the document is held, and the last good version stays published; that may be the corrected text. The hold reason says "the source sent a new text; your correction to the previous one no longer applies" and links to the old diff, so the curator can apply it again.

  No conflict record is needed, because this follows from the data.
- **Withdrawable:** the document goes back to its source text, and is re-parsed and re-checked.
- **Audited:** `correct_text` and `withdraw_text_correction` rows in `curation.audit_log`, with the sha256 values before and after and the reason. Both texts stay in the blob store, so the exact change can always be shown.

## What happens to the review queue

| Item kind | Today | After |
|---|---|---|
| `structure_suspect` | Opened by parse | **No longer opened.** The structure check is a hold reason |
| `unresolved_id` | Opened by load | **No longer opened.** The identity check is a hold reason |
| `unresolved_citation`, `conflict`, `quarantine` | Review page | Unchanged |

The settle step keeps only its citation rule. Its structure and identity rules go, because no new items of those kinds are opened.

Open items of the two retired kinds are closed once, at rollout, by the platform curator, with the note "replaced by the publish gate".

The **Review** page stays for the remaining kinds. **Held documents** becomes its own page, with its count on the overview.

## Implementation

The layers and the dependency rule are unchanged (`tests/test_architecture.py`).

### Domain (pure)

| Module | Change |
|---|---|
| `domain/gate.py` (new) | `MainText` (effective sha256, parsed sha256, parser version, problems) and `Approval` (text sha256, problems). `hold_reasons(document_id, main_texts, approvals, roles, parser_version) -> tuple[str, ...]`; empty means the document passes. |
| `domain/publishing.py` | `effective_texts(texts, corrections)`, next to `effective_values`. `DocumentSnapshot` gains `main_texts`, `approvals` and `corrections`. `publication_of` publishes effective texts and is otherwise unchanged. |
| `domain/curation.py` | `checked_text_correction(current, corrected, *, paged) -> str`: the normalised text, or `InvalidCorrection`. |
| `domain/reviews.py` | Only the citation rule remains; `TextStanding` moves into `gate.py` as `MainText`. |

### Application

| Module | Change |
|---|---|
| `publish.py` | Order: remove, hold (no write), publish. `PublishReport.held`. |
| `curate.py` | `correct_text`, `withdraw_text_correction`, `approve`, `withdraw_approval`. |
| `parse_texts.py` | Parses each main text's effective content and records `parsed_sha256`. Stops opening `structure_suspect` items. |
| `load_bundle.py` | Stops opening `unresolved_id` items. |
| `views.py` | The held list (reasons, last published date, filter by reason). The document view gains its publish state, hold reasons, approvals and the correction diff. |
| `settle_reviews.py` | Citations only. |
| `ports.py` | `CurationActions` gains the four actions. The snapshot and the text-to-parse records gain their new fields. |

### Adapters

| Where | Change |
|---|---|
| Migration `0009_publish_gate.sql` | Tables `curation.approval` and `curation.text_correction` (shaped like `curation.override`: author, reason, `created_at`, `active`; FKs to `registry.document` with `ON UPDATE CASCADE`, so an assigned ID carries them along). Column `registry.text_version.parsed_sha256`, backfilled with `sha256` where the text is parsed. The one-time rollout steps below. |
| `postgres/derived.py` | `_TEXTS_TO_PARSE` selects current main texts where `parsed_with` or `parsed_sha256` differs from today's, and reads the effective blob. |
| `postgres/publishing.py` | Snapshot parts for main texts, approvals and corrections. `_TO_PUBLISH` also picks documents with an approval or correction newer than their publication, as it already does for overrides. |
| `postgres/curation.py` | The four actions, each in one transaction with its audit row. Each touches `registry.document.updated_at`. |
| `web/` | A **Held documents** page. The document page gets a state banner, the Structure section gets **Approve as is**, and there is an **Edit text** page. `after_change` runs parse, then publish. |
| `cli.py` | `build` is unchanged in order. `publish` and `build` print `held`. |

### Documentation

- `README.md`: the build table, and the held list in the curation section.
- `docs/published-schema.md`: one paragraph: "Only documents that pass the platform's checks are published. A document that later fails keeps its last published version until it passes again."

## Rollout

1. **Build first:** every main text must be parsed by the current parser. As of 2026-10-19 all are, by parser 4.
2. **Apply migration 0009.** Its one-time steps:
   - Withdraw from `published` every document that fails the gate today, so the invariant holds from the start. These versions were never good. Each gets a `removed` row in `published.change_log`, so the Knowledge and Retrieval layer drops them. Expected: **95 documents** (69 structure, 24 without a main text, 3 placeholders), leaving **2,497** published. No approvals or corrections exist yet, so the SQL needs only the stored problems, the IDs and the file roles.
   - Close the open `structure_suspect` (69) and `unresolved_id` (3) items as the platform curator, with audit rows.
3. **Deploy the code**, then run `metamorph build`. Expect `held: 95` and no other change.
4. **Curators work the held list.** The 24 BI documents go to the BI connector's re-fetch, which is already pending.

## Testing

Tests are written first (TDD), matching the existing suites:

- **Domain:**
  - every hold reason, and passing;
  - an approval that matches and one that has lapsed;
  - effective texts with and without a correction;
  - text-correction validation, including page markers.
- **Application, with fakes:**
  - a held document with a published version is left untouched, and one without stays out;
  - suppression beats the gate;
  - a correction leads to a re-parse, then a pass, then publishing;
  - the `held` count.
- **PostgreSQL:**
  - load → parse → publish holds a gappy text;
  - a text correction re-parses and publishes it, with offsets matching the corrected blob;
  - a new source text makes the correction lapse, and the last good version stays;
  - an approval lapses when the parser changes the problems;
  - the rollout steps of the migration.
- **Web:** the four new forms, including validation errors shown beside their field.

## Trade-offs and risks

| Risk | Why we accept it | Mitigation |
|---|---|---|
| A held document's last good version **falls behind**: changes to its status, links or validity don't reach `published` until it passes again | Holding the whole document keeps D1 simple, with no version history and no partial publishing | Held documents with a published version are listed first, and the overview shows their count. A status change matters most for a legal assistant, so these are worked first |
| One curator's text edit is published once it passes the parse check, and that check validates structure, not wording (D2) | Speed and simplicity at this stage | A required reason naming the source, a full diff on the document page, the audit log, and withdrawal in one step |
| Corrected text is indistinguishable in `published` (D3). Its `method` may still say `ocr` | The user's decision | Full provenance stays internal: correction rows, both blobs, audit log |
| Approvals lapse whenever the parser changes a text's problems | A changed reading deserves a fresh look | Only documents whose problems actually changed lapse |
| Text editing could become the default fix for parser bugs | Editing is the simplest universal fix for a single document | Filtering the held list by reason shows patterns. When several documents fail the same way, fix the parser or the connector |

## Out of scope

- A second curator's approval (D2).
- A corrected-text marker in `published` (D3).
- A structure editor: marking headings or editing provisions.
- Version history in `published`.
- Bulk actions, notifications, and a rich-text or side-by-side editor.
- Editing annexes, FAQs, abstracts or Arabic texts: only main texts are parsed and gated.
- Holding documents for unlinked citations, and an ID scheme for Bapepam or BI SK Direksi instruments.
