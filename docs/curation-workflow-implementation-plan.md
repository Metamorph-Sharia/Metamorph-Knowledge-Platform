# Plan: implementing the curation workflow with a publish gate

**Design:** [curation-workflow-design.md](curation-workflow-design.md). Its decisions are taken as given: D1 last good version, D2 no second approval, D3 no corrected-text label.
**Date:** 2026-10-19
**Approach:**
- Clean Architecture: rules in `domain/`, use cases and ports in `application/`, SQL and HTTP in `adapters/`, the dependency rule enforced by `tests/test_architecture.py`.
- Kent Beck's way of working: a test list per step, red → green → refactor, structure changes ("tidy first") kept apart from behaviour changes, and every step ends green and committable.

## Progress

| Step | State |
|---|---|
| R1, steps 1.1–1.9 | **Built, 2026-10-19.** 338 tests pass with PostgreSQL and S3; lint clean. The rollout is **not applied** to the live database yet: a read-only dry run of migration 0010 selects 95 documents to withdraw (2,497 stay published) and 72 review items to close (69 structure, 3 identity), as planned |
| R1 rollout | Applied by the user, 2026-10-19: 95 held, 2,497 published |
| R2, steps 2.1–2.7 | **Built, 2026-10-19.** 372 tests pass with PostgreSQL and S3; lint clean. Migration `0011_text_correction.sql` is **not applied** to the live database yet. Dry run on the live data, in one rolled-back transaction with the corrected wording kept in memory: `id:permenko-perekonomian:2024:13`, whose PDF extraction split "Pasal" and "4" over two lines, was corrected, parsed clean (52 provisions), published with all 52 provision bodies matching the corrected text, and left the hold list; the other 94 stayed held |

Three small departures from the steps below, each simpler than planned:
- **Two migrations, not one.** `0009_publish_gate.sql` holds the tables. `0010_publish_gate_rollout.sql` holds the one-time withdrawal and the closing of retired items, so it is tested on its own against a database at 0009 (`tests/test_publish_gate_rollout.py`, which also checks it withdraws exactly what the domain gate would hold).
- **`MainText` has no `parsed_sha256` in R1.** Until texts can be corrected, the parsed content is always the text itself. The field and its test arrive with R2 (step 2.1), where they have a job.
- **No `_TO_PUBLISH` clause for approvals.** Approving or withdrawing touches the document's `updated_at`, which the publish step already watches; held documents are re-evaluated on every run anyway.

And in R2:
- **Page markers are `<!-- page N -->`,** the contract's convention (`metamorph_contract.split_pages`), not `=== page N ===` as step 2.2 says.
- **Correcting is its own small use case, `CorrectText`** (in `application/curate.py`, sharing the reason rule), because it needs ports `Curate` doesn't: `CorrectableTexts` (where a text's effective content is) and the blob store. Curators' other actions are unchanged.
- **Effective texts reach the gate through the domain:** the snapshot carries main texts as the sources sent them, and `hold_reasons_of` reads each through its correction, so the "effective text" rule lives once, in `domain/publishing.py`. Only the parse query applies it in SQL, because choosing what to parse is a query.
- **An approval names the text's effective content,** so a corrected text's remaining problems can be approved; approving before the correction is parsed is refused.
- **The changes are shown on their own page** (`/documents/{id}/texts/{sha}/correction`), not on the document page, so the document page reads no extra blobs.
- **The rollout test now runs 0010's SQL on a fully migrated database,** set back to how the platform published before the gate: today's code can't build a database stopped at 0009.

## Releases

The work ships in **two releases**. Within a release, each step can be merged on its own and the build stays green, but nothing changes for curators until the release is cut.

| Release | Contains | Why together |
|---|---|---|
| **R1: the gate** | Hold reasons, publish keeps the last good version, the held list, approve as is, retiring the `structure_suspect` and `unresolved_id` items, the rollout migration | The gate must go live together with the withdrawal of today's 95 failing documents, or they would stay published as if they were good: a held document is never written. Approve as is must come with it, so a genuine gap isn't held with no way out. The retired review items must stop at the same moment, or a document would be both held and queued. |
| **R2: text correction** | Edit text, parse the effective text, publish the effective text, and the correction lapsing when the source sends a new text | Independent of R1's rollout, and the largest piece; it gets its own review. |

## Clarifications to the design

Reading the code brought out two details. Neither changes the design's behaviour.

1. **Hold reasons are stored, not recomputed per page view.** The publish step evaluates the gate and records each held document's reasons in a new derived table, `registry.hold`, rewritten as documents are evaluated. Computing the gate for 2,592 snapshots on every page load would be too slow. The list is still derived: no curator opens or closes anything, and a document leaves the table the moment it passes. The README's "written by" column for `registry` gains "the publish step (holds)".
2. **The connectors send no provisions.** All 311,738 provisions are `origin = 'parsed'`. A corrected text therefore only ever has parsed provisions, cut from its own content. If a connector ever sends provisions for a text that has a correction, they are not published for it. Their offsets point into the source wording, not the corrected one.

## Architecture review of the change

| Ring | New or changed | Depends on |
|---|---|---|
| Domain | `gate.py` (new): `MainText`, `Approval`, `HoldReason`, `hold_reasons()`. `publishing.py`: `effective_texts()`, `must_be_removed()`. `curation.py`: `checked_text_correction()` | stdlib, `metamorph_contract` (its paged-text convention), other domain modules |
| Application | `publish.py` (hold branch), `curate.py` (four actions), `parse_texts.py` (effective content, no queueing), `settle_reviews.py` (citations only), `views.py` (held list), `ports.py` | domain, ports |
| Adapters | `postgres/publishing.py`, `postgres/derived.py`, `postgres/curation.py`, `postgres/views.py`, migration 0009, `web/` | application ports, domain |
| Entry points | `wiring.py`, `cli.py` | everything |

Checks against the skill's list:
- **The dependency rule holds.** Every new rule is pure domain logic. The use cases see only ports.
- **Rules live in one place each.** "Effective text" sits next to "effective values", and both are domain. The gate is domain. SQL only selects and stores.
- **Ports stay segregated.** The publish step gets a new, narrow `HoldList` port rather than a wider `PublishedStore`. `BlobStore` gains `put()` for bytes, so the use case never creates temporary files. `CurationActions` gains four methods, the same shape as the existing ones.
- **No speculative generality.** There is no state machine, no rule engine, no plugin checks, no publication history and no feature flags. There are four checks, written out.
- **Simple data crosses the boundaries.** The snapshot gains plain frozen dataclasses. The views get plain rows.

## Release 1: the gate

### Step 1.1 (tidy): make removal an explicit rule

*Structure only, no behaviour change.*
- Extract `must_be_removed(snapshot) -> bool` from `publication_of` in `domain/publishing.py`: the "suppressed, or no source record" condition. `publication_of` stays the same for callers.
- `Publish.run` calls `must_be_removed` first, then `publication_of`.

Tests: the existing `test_publish.py` passes unchanged. Add one direct test of `must_be_removed`.

### Step 1.2: hold reasons (domain)

Add `domain/gate.py`:

```text
MainText(sha256, parsed_sha256, parsed_with, problems)    # effective content, and what was parsed
Approval(text_sha256, problems)
HoldReason(check, detail)                                 # check ∈ identity | text | parsed | structure
hold_reasons(document_id, main_texts, approvals, other_roles, parser_version) -> tuple[HoldReason, ...]
```

Test list (`tests/test_gate.py`):
- [ ] A canonical ID with one main text that is parsed and clean passes (no reasons).
- [ ] A placeholder ID (`unresolved:…`) is held with `identity`.
- [ ] No main text is held with `text`, and the detail names the roles that were acquired ("faq, abstract").
- [ ] A main text not parsed by today's parser is held with `parsed`.
- [ ] A main text whose parsed content differs from its effective content (a correction not parsed yet) is held with `parsed`.
- [ ] Structure problems are held with `structure`; the detail lists the first `MAX_PROBLEMS_SHOWN`.
- [ ] An approval for that text and exactly those problems passes.
- [ ] An approval for that text with other problems, or for another text, doesn't.
- [ ] Several failing checks give several reasons, in a stable order.

Move `MAX_PROBLEMS_SHOWN` into `gate.py`. Parsing and the views import it from there.

### Step 1.3: the snapshot carries what the gate needs

- `DocumentSnapshot` gains `main_texts: tuple[MainText, ...]` and `approvals: tuple[Approval, ...]`. Each defaults to empty, so existing tests keep compiling.
- `PostgresPublication.snapshot` adds two parts:
  - **main texts**, built on the shared `MAIN_TEXT` fragment. Until R2, `sha256` and `parsed_sha256` are the same column.
  - **approvals**, the active rows of `curation.approval`.
- Migration `0009_publish_gate.sql`, part 1:
  - `curation.approval`: id, document_id (FK, `ON UPDATE CASCADE`), text_sha256, problems jsonb, author FK, reason, created_at, active. Shaped like `curation.override`.
  - `registry.hold`: document_id PK (FK, `ON UPDATE CASCADE`, `ON DELETE CASCADE`), reasons jsonb, held_since timestamptz.

Tests:
- [ ] `test_postgres_publishing`-style DB test: the snapshot of a gappy text has its problems, and the snapshot of an approved document has its approval.
- [ ] `test_migrations`: 0009 applies to an empty database and to one at 0008.

### Step 1.4: publish holds, keeping the last good version

`Publish.run`, for each document it would refresh:

```text
snapshot is None or must_be_removed(snapshot)  → published.remove(id); holds.clear(id)
reasons := hold_reasons(...)                    → holds.record(id, reasons); report.held += 1   (no write to published)
otherwise                                       → published.replace(publication_of(...)); holds.clear(id)
```

- New port `HoldList` with `record(document_id, reasons)` and `clear(document_id)`, implemented by `PostgresPublication`, which owns the transaction.
- `PublishReport` gains `held`.
- `_TO_PUBLISH` gains `OR EXISTS (approval newer than the publication)`, as it already has for overrides.
- Held documents are picked again on every run without extra SQL: `updated_at > published_at` stays true, or they were never published.

Test list (`tests/test_publish.py`, with fakes):
- [ ] A failing document with a published version is left exactly as published, and the store sees no write.
- [ ] A failing document never published stays unpublished.
- [ ] Both are recorded as held with their reasons, and counted.
- [ ] A held document that passes later is published, and its hold is cleared.
- [ ] Suppression beats the gate: removed, not held.
- [ ] `publish --all` doesn't withdraw a held document's last good version.

DB test (`tests/test_postgres_publishing.py`):
- [ ] Load a clean text, then build: published. Reload with a gappy text, then build: the published rows are byte-for-byte the clean version, no `change_log` row is added, and `registry.hold` has the reason.

### Step 1.5: approve as is

- **Domain:** none beyond Step 1.2. The reason is checked by the existing `_reason`.
- **Application:** `Curate.approve(curator, document_id, text_sha256, reason)` and `Curate.withdraw_approval(...)`. The problems approved are the ones stored for that text when the curator approves, read in the adapter's transaction, so a curator can't approve problems they haven't seen.
- **Adapter:** `PostgresCurationActions.approve` / `withdraw_approval`. Each runs in one transaction, writes an audit row (`approve`, `withdraw_approval`), and touches `updated_at`. Approving a text that has no problems is refused (`CurationRefused`).

Tests:
- [ ] `test_curate.py`: the reason is required, and the call is delegated.
- [ ] `test_postgres_curation.py`: approve leads to an audit row and the document published on the next run. Withdraw leads to held again. A re-parse that changes the problems makes the approval lapse, and the document is held.

### Step 1.6: stop opening `structure_suspect` and `unresolved_id` items

*Behaviour change.* The gate is now the signal.
- `ParseTexts` no longer takes a `ReviewQueue`. `ParseReport.suspect` stays as a count. Remove `_queue`.
- `LoadBundle` no longer opens `unresolved_id`; conflict and quarantine items stay.
- `PostgresCurationActions.assign_id` no longer closes `unresolved_id` items (dead code once none are opened).
- `SettleReviews` keeps only the citation rule:
  - remove `structure_settlement`, `identity_settlement` and `ABOUT_A_DOCUMENT`'s structure half;
  - `OpenReviews` loses `text_standing`;
  - `TextStanding` is deleted.
- `REVIEW_KINDS` and `web/presentation.py` drop the two kinds.

Tests to change: `test_derive.py`, `test_load_bundle.py`, `test_postgres_loading.py`, `test_postgres_curation.py`, `test_postgres_reviews.py`, `test_settle_reviews.py`, `test_review_rules.py`, `test_web.py`. Each change is an assertion that the item is *not* opened, or an assertion removed with its rule. No test is deleted without its behaviour going too.

### Step 1.7: the held list and the document's state (views and web)

- `CurationViews.held_page(check: str | None, page)` returns `HeldPage(rows, counts_by_check)`. Each `HeldRow` has document_id, title, reasons, `published_at` (None if never published) and `held_since`. Rows with a published version come first, then `held_since`.
- `DocumentView` gains `state`: published, held (with reasons and the last good version's date) or suppressed. It also gains `approvals`.
- `Dashboard` gains `held` and `held_with_published_version`.
- **Web:**
  - `GET /held?check=` page.
  - A state banner on the document page.
  - **Approve as is** and **Withdraw** forms in the Structure section.
  - A nav link and a count on the overview.

Tests:
- [ ] `test_web.py` (fake views): the held page lists rows and filters by check; the banner says held, with its reasons; the approve form posts with CSRF.
- [ ] `test_web_postgres.py`: approve from the page leads to the document published and the banner showing *Published*.

### Step 1.8: rollout migration

`0009_publish_gate.sql`, part 2, one time only:
- **Withdraw from `published`** every document that fails the gate now, written in SQL over stored facts. No approvals exist yet, and every main text is parsed by parser 4:
  - a placeholder ID;
  - no `MAIN_TEXT` row;
  - or a main text with non-empty `structure_problems`, or `parsed_with` not equal to the current version.

  Each withdrawal gets a `removed` row in `published.change_log`.
- **Close the open `structure_suspect` and `unresolved_id` items** as `metamorph-platform`, with the note "replaced by the publish gate" and audit rows. The curator row is upserted first.

Tests (`test_migrations.py`, DB):
- [ ] A published document that fails is withdrawn and logged as `removed`; a passing one is untouched.
- [ ] Open items of the retired kinds are closed and audited; other kinds are untouched.

**Dry run before merging:** run the withdrawal's `SELECT` on the live database inside a transaction that is rolled back. Expect **95** documents (69 structure, 24 without a main text, 3 placeholders) and 2,497 left published.

### Step 1.9: documentation, and cutting R1

- `README.md`:
  - the build table: `publish` reports `held`, and `settle` handles citations only;
  - the curation section: the held list;
  - the "written by" column for `registry`.
- `docs/published-schema.md`: the gate paragraph from the design.
- The design doc's status becomes "R1 implemented".

**Done when:**
- the full suite passes, with the database and S3;
- `ruff check` and `ruff format --check` are clean;
- the architecture test passes;
- after the migration, `metamorph build` on the live database prints `held: 95` and changes nothing else;
- the held list shows the 95 documents, with the 24 BI documents filterable under `text`.

## Release 2: text correction

### Step 2.1 (tidy): the content to parse is named for what it is

*Structure only.* `TextToParse.sha256` and `storage_key` are already used only to read and record the content. Document them as "the content to parse", and add `parsed_sha256` to what `ParsedTexts.save` records:
- Migration 0010 adds `registry.text_version.parsed_sha256`, backfilled with `sha256` where the text is parsed.
- `save` writes it.
- The snapshot's `MainText.parsed_sha256` now reads this column.

Tests: existing parse tests pass. Add one asserting that `parsed_sha256` is recorded.

### Step 2.2: the correction rule (domain)

`domain/curation.py`: `checked_text_correction(current: str, corrected: str, *, paged: bool) -> str`.

Test list (`tests/test_curation_rules.py`):
- [ ] Returns the text with `\n` line endings and a final newline.
- [ ] Empty or whitespace-only text is refused.
- [ ] Text identical to the current text, once normalised, is refused.
- [ ] For a paged text, a missing, added or reordered `=== page N ===` marker is refused, and the message names the page. This reuses `metamorph_contract`'s paged-text convention rather than a new pattern.
- [ ] An unpaged text may contain anything.

### Step 2.3: effective texts (domain)

`domain/publishing.py`: `TextCorrection(corrects_sha256, sha256, storage_key)` and `effective_texts(texts, corrections) -> tuple[StoredContent, ...]`. A corrected text takes the correction's `sha256` and `storage_key`, and keeps its own rights and details: language, origin, method, paged, of_file (D3). `publication_of` publishes effective texts. `DocumentSnapshot` gains `corrections`.

Test list:
- [ ] Without a correction, texts are unchanged.
- [ ] A correction replaces `sha256` and `storage_key` and nothing else.
- [ ] A correction of a text that isn't current has no effect.
- [ ] Provisions parsed from the corrected content are published with the corrected text; offsets match the corrected wording.
- [ ] `curated` stays false when only the text was corrected.

### Step 2.4: parse the effective text

- Migration 0010 adds `curation.text_correction`: id, document_id (FK, `ON UPDATE CASCADE`), corrects_sha256, sha256, storage_key, author FK, reason, created_at, active. A unique index allows one active row per `(document_id, corrects_sha256)`.
- `_TEXTS_TO_PARSE`:
  - `LEFT JOIN` the active correction of each current main text, so the content to parse is the correction's `sha256` and `storage_key` if there is one, otherwise the text's own;
  - select where `parsed_with` differs from today's parser, **or** `parsed_sha256` differs from that effective `sha256`.
- The snapshot's main texts and texts read the same effective content. Provisions are read with `t.parsed_sha256` as their `text_sha256`.

DB tests (`tests/test_postgres_derived.py`):
- [ ] A text with an active correction is parsed from the corrected blob, and `parsed_sha256` is the correction's.
- [ ] Withdrawing the correction leads to a re-parse from the source blob.
- [ ] A second parse run changes nothing.

### Step 2.5: correct and withdraw (use case and adapter)

- `BlobStore` gains `put(sha256, data: bytes, media_type) -> StoredBlob`, implemented by `S3BlobStore` and `MemoryBlobStore`.
- `Curate.correct_text(curator, document_id, text_sha256, raw, reason)`:
  1. read the current effective text and its `paged` flag (a read port);
  2. `checked_text_correction`;
  3. `blobs.put`;
  4. `actions.correct_text(curator, document_id, text_sha256, sha256, storage_key, reason)`.
- `Curate.withdraw_text_correction(...)`.
- `PostgresCurationActions.correct_text`:
  - refused unless `text_sha256` is a current main text of the document;
  - deactivates the previous correction;
  - inserts the new one;
  - writes an audit row (`correct_text`, before and after sha256);
  - touches `updated_at`;
  - all in one transaction.

Tests:
- [ ] `test_curate.py` (fakes): the validation error reaches the caller unchanged; the blob is stored before the action; the reason is required.
- [ ] `test_postgres_curation.py`: a correction is audited, and a second correction replaces the first. A correction of a text that isn't current is refused.

### Step 2.6: immediate re-check (web)

- `WebServices` gains `parse: ParseTexts`. `after_change` runs `parse.run()` and then `publish.run()`. It already publishes; parsing only reads changed texts, so this is cheap.
- `GET /documents/{id}/texts/{sha}/edit` shows a text area holding the effective text, the reason field, and validation errors beside their field.
- `POST /documents/{id}/texts/{sha}/correction` and `POST …/correction/withdraw`.
- The document page shows a diff of the source text against the correction (`difflib`, computed in the view adapter), and the correction's author, reason and time.
- When a correction lapsed because the source sent a new text, the held banner says so and links to the old diff. That comes from the latest inactive correction whose `corrects_sha256` is no longer current.

Tests:
- [ ] `test_web.py`: the edit page renders; a broken page marker comes back as a 422 with the message beside the field; CSRF is required.
- [ ] `test_web_postgres.py`, end to end:
  1. A gappy text is held.
  2. The curator fixes "Pasa1 3" through the form.
  3. Within the same request it is parsed clean and published.
  4. The published `text.sha256` is the corrected one, and the provision bodies match it.
- [ ] `test_web_postgres.py`: a reload with a new source text leads to the correction lapsing; if the new text fails, the last good, corrected version stays published and the banner shows the lapse.

### Step 2.7: documentation, and cutting R2

- `README.md`, curation section: editing text.
- The design doc's status becomes "implemented".

**Done when:**
- the suite, lint and architecture test are green;
- on a copy of the live database, one held document is corrected through the app, published, and its provisions and published text agree.

## Working agreements for every step

- **Test first.** Write the step's test list as failing tests, make them pass with the simplest code, then refactor while green.
- **Separate commits for structure and behaviour.** Steps 1.1 and 2.1 are tidyings and change no behaviour.
- **Small steps.** If a step's diff gets hard to review, split it rather than finishing it in one go.
- **Clear `__pycache__` before validating.** A stale `.pyc` has hidden an edit in this repo before.
- **Run the full suite with the database and S3:**
  ```bash
  uv run -q --env-file .env.example env METAMORPH_TEST_DATABASE_URL=postgresql://metamorph:metamorph-dev@localhost:5433/postgres METAMORPH_TEST_S3_ENDPOINT_URL=http://localhost:8333 pytest -q
  uv run -q ruff check src tests && uv run -q ruff format --check src tests
  ```
- **Live-database checks** are read-only and rolled back, until the release is cut.

## Risks to watch during implementation

| Risk | Where | Guard |
|---|---|---|
| The rollout migration's SQL differs from the domain gate | Step 1.8 | A DB test runs both on the same fixtures and compares the document sets. The migration runs once; afterwards only the domain rule decides |
| The web app's parse runs at the same time as a scheduled `build` | Step 2.6 | `ParsedTexts.save` already replaces a text's rows in one transaction, so a double parse writes the same result |
| Held documents are re-evaluated on every publish | Step 1.4 | About 95 snapshots per run; measure the build time before and after, and stop if it grows noticeably |
| A large text (1.8 MB at most) in a text area | Step 2.6 | Accepted by the design. Check the largest text in a browser before cutting R2 |
