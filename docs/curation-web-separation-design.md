# Design and migration plan: the curation web app in its own repository

**Status:** done, 2026-10-19. All four phases: the JSON API, the new repository, every page, and the cut-over, with the old app retired
**Scope:** where the curation web app lives, how it talks to the platform, and how it moves without interrupting curation. The domain, the use cases, the pipeline, the database and the `published` contract don't change.
**Related:** [curation-workflow-design.md](curation-workflow-design.md) describes the workflow the app serves.

## Summary

The curation web app moves to a new repository, **`Metamorph-Curation-Web`**, rebuilt in **Next.js (App Router) and TypeScript**. It talks to the platform only through a versioned **JSON API**, which the platform repository serves as one more adapter over the use cases it already has.

The move happens page by page while the current app keeps running, then the current app is retired. Curators keep working throughout, and nothing upstream of the web app changes.

## Constraints

| # | Constraint | Source |
|---|---|---|
| C1 | The web app gets its own repository | User |
| C2 | The frontend is Next.js and TypeScript | User |
| C3 | The structure of `Metamorph-Knowledge-Platform` stays as it is: no package or component is moved, renamed, split or reorganized | User |
| C4 | Curation is never interrupted, and nothing upstream of the web app changes (pipeline, database, `published`) | Minimal disruption |

Within C3, the platform repository's changes are:
- **Additions inside its existing layout:**
  - a JSON adapter `adapters/api/`, a sibling of the existing `postgres/`, `blobs/` and `web/` adapters;
  - one CLI command, `metamorph api`;
  - one compose service, `api`.
- **One deletion at cut-over:** the old HTML adapter, `adapters/web/`. Deleting it is the move itself. The one file it holds that the API also needs, `accounts.py`, goes to `adapters/api/` at that point.

## Where we start

The current app is a thin, server-rendered adapter:
- **About 2,600 lines**, counting its read models and their SQL.
- **23 routes:** 9 pages, 13 curator actions, one file stream and a health check.
- **No business logic in any route.** Every route calls a use case (`Curate`, `CorrectText`, `AddManualDocument`, `Publish`, `ParseTexts`) or a read model (`CurationViews`).
- **Plain data at the boundary.** The read models are frozen dataclasses, and every rule (the publish gate, validation, audit) sits in `domain/` and `application/`.
- **Nothing depends on it.** Nothing outside `adapters/web/` imports it, apart from its own tests and the `metamorph web` entry point.

This is what makes the move cheap: a second delivery mechanism plugs into the same ports.

## Architecture decisions

### ADR-1: the API is an adapter in the platform repository; only the frontend moves out

**Decision.** The JSON API lives in the platform repository as `adapters/api/`, served by the platform image (`metamorph api`). The new repository holds only the Next.js app.

**Options considered:**

| Option | For | Against |
|---|---|---|
| **A. API adapter in the platform repository** (chosen) | The dependency rule holds as it does today: the adapter depends inward on application ports. One release carries a rule change and the endpoint that exposes it. It's tested with the same in-memory fakes. One image, one deployment unit | The platform repository gains an adapter (additive; within C3) |
| B. A Python API in the new repository, importing `metamorph-platform` as a pinned package | The platform repository is untouched | The API then depends on the platform's application layer and its `wiring.py` across a repository boundary, so every use-case change needs a coordinated release of both repositories. Migrations, wiring and the API's tests split across two places. Two Python services share one database's rules |
| C. Next.js reads PostgreSQL directly (API routes or server actions with SQL) | Fewest moving parts at first | It bypasses the use cases: the publish gate, validation and audit would be rewritten in TypeScript or skipped. Two writers to `curation` with different rules. It breaks the dependency rule outright |

**Clean Architecture review:**
- **The dependency rule.**
  - `adapters/api` → `application` → `domain`, exactly like `adapters/web` today. `tests/test_architecture.py` already enforces it for every adapter, with no change.
  - The Next.js app depends only on the HTTP contract, never on Python code or the database.
- **Crossing boundaries.** Data leaves the platform as JSON documents described by an OpenAPI schema (see ADR-3). Domain objects never reach the browser as anything but plain values.
- **The use cases are the API.** Each action endpoint calls exactly one use-case method, and each page endpoint calls one read model. No rule is re-implemented in the adapter or in TypeScript.
- **SRP:** one adapter per delivery mechanism. `adapters/web` serves HTML forms and `adapters/api` serves JSON, each changing for its own reason; neither changes when a rule changes.
- **ISP:** the API gets its own small service bundle (`ApiServices`) instead of reusing the HTML app's `WebServices`. When the HTML adapter goes, nothing else has to change.
- **No speculative layers.** There is no API gateway, no separate backend-for-frontend service and no GraphQL. The Next.js server is the only caller, and the API is shaped for the pages and actions that exist.

### ADR-2: the browser talks only to Next.js; the API is private

**Decision.**
- The browser calls only the Next.js server: server components to read, server actions to change.
- The Next.js server calls the API over the private network.
- The API is never exposed to the internet.

**Why:** one public surface, no CORS, and no API token held in the browser. It also lets the API stay simple: it trusts a signed token and checks nothing browser-specific.

### ADR-3: the contract is the OpenAPI document, versioned and checked in CI

**Decision.**
- **The API publishes its OpenAPI document** (FastAPI generates it). It's committed as `docs/api/openapi.json` in the platform repository, and a test fails if the API and the committed file differ.
- **The frontend generates its TypeScript types** from that file (`openapi-typescript`). A breaking change shows up as a compile error, not a runtime surprise.
- **Paths are versioned** (`/api/v1/...`). A breaking change gets `/api/v2` while v1 is still served.
- **Response models are the existing read models** (`application/views.py`): they are already plain, immutable, presentation-shaped data. An API-specific model is added only where JSON needs a different shape. One known case: domain enums such as `Check` are serialized as their string values.

### ADR-4: sign-in reuses today's accounts and adds a token

**Decision.**
1. **Sign-in:** Next.js shows a sign-in form and calls `POST /api/v1/auth/session` with the username and password.
2. **Token:** the API verifies them against today's curator accounts (`METAMORPH_CURATORS`, PBKDF2 hashes, unchanged). It returns a short-lived token signed with `METAMORPH_WEB_SECRET`, carrying the username, display name and expiry.
3. **Storage:** Next.js keeps the token in an httpOnly, Secure, SameSite=Lax cookie, and sends it as `Authorization: Bearer` on every API call.
4. **The curator on each action** comes from the token. The audit log keeps naming the right person.
5. **CSRF** is covered by Next.js server actions (which check the origin) and the SameSite cookie. The form-token code of the HTML app is not carried over.

**Later, without touching the endpoints:** replace the accounts with an identity provider (Cognito, or Google Workspace via OIDC). Next.js signs curators in; the API verifies the provider's tokens instead of its own.

### ADR-5: files move through S3 directly, not through two servers

**Decision.**
- **Opening a file or text:** the API returns a short-lived presigned S3 URL; it doesn't stream the bytes.
- **Uploading a manual document (up to 100 MB):**
  1. Next.js asks the API for a presigned upload URL;
  2. the browser uploads straight to S3;
  3. Next.js submits the form with the object's key;
  4. the API reads the object and calls `AddManualDocument` as it does today. The use case is unchanged.
- **Text correction stays JSON** (1.8 MB at most).

**Locally**, SeaweedFS issues presigned URLs the same way.

### ADR-6: the immediate re-check stays in the API

**Decision.** Every action endpoint does what the HTML app's `after_change` does: run the use case, then parse what changed, then publish, and only then answer.

**Why:** the curator sees *Published* or *Held: …* in the response, and every future client gets the same behaviour for free.

## The API

All routes are under `/api/v1` and need a bearer token, except `auth/session` and `/healthz`.

### Reads

| Endpoint | Returns | Replaces |
|---|---|---|
| `GET /overview` | `Dashboard` | `GET /` |
| `GET /held?check=&page=` | `HeldPage` | `GET /held` |
| `GET /reviews?kind=&page=` | `ReviewPage` | `GET /review` |
| `GET /documents?q=` | `DocumentRow[]` | `GET /documents` |
| `GET /documents/{id}` | `DocumentView` | `GET /documents/{id}` |
| `GET /documents/{id}/texts/{sha}/editable` | `EditableText` and its current wording | `GET …/edit` |
| `GET /documents/{id}/texts/{sha}/correction` | `CorrectionView`, both wordings and the diff | `GET …/correction` |
| `GET /documents/{id}/content/{sha}` | A presigned URL (ADR-5) | `GET …/content/{sha}` |
| `GET /auth/session` | The signed-in curator | (new) |

### Actions

Each takes `reason`. Each answers `200` with the document's state after the re-check (ADR-6), `422` for invalid input, or `409` when the action is refused.

| Endpoint | Use case |
|---|---|
| `POST /documents/{id}/corrections` `{field, value}` | `Curate.correct` |
| `POST /documents/{id}/corrections/{field}/withdraw` | `Curate.withdraw_correction` |
| `POST /documents/{id}/texts/{sha}/approval` | `Curate.approve` |
| `POST /documents/{id}/texts/{sha}/approval/withdraw` | `Curate.withdraw_approval` |
| `POST /documents/{id}/texts/{sha}/correction` `{wording}` | `CorrectText.correct` |
| `POST /documents/{id}/texts/{sha}/correction/withdraw` | `CorrectText.withdraw` |
| `POST /documents/{id}/suppression` (requires `confirm: true`) | `Curate.suppress` |
| `POST /documents/{id}/restore` | `Curate.restore` |
| `POST /documents/{id}/id` `{new_id}` | `Curate.assign_id` |
| `POST /documents/{id}/citations/{citation_id}/link` `{target_id}` | `Curate.link_citation` |
| `POST /documents/{id}/conflicts/{conflict_id}` `{decision}` | `Curate.resolve_conflict` |
| `POST /reviews/{item_id}` `{state}` | `Curate.decide_review` |
| `POST /uploads` | A presigned upload URL (ADR-5) |
| `POST /documents` `{…fields, upload_key}` | `AddManualDocument.run` |
| `POST /auth/session` `{username, password}` | Sign-in (ADR-4) |

### Errors

The bodies follow what the use cases already raise:

| Status | Body | Raised as |
|---|---|---|
| `422` | `{"error": "invalid", "message": "…", "fields": {…}}`: `fields` is empty for `InvalidCorrection`, and has one message per field for `InvalidManualDocument` | `InvalidCorrection`, `InvalidManualDocument` |
| `409` | `{"error": "refused", "message": "…"}` | `CurationRefused` |
| `401` | `{"error": "unauthorized", "message": "…"}` | No token, a forged one, or an expired one |
| `404` | `{"error": "not_found", "message": "…"}` | No such document, text, check or queue |

## The new repository: `Metamorph-Curation-Web`

```
app/                    App Router: one route per page; server components read, server actions change
  (signed-in)/held/ · review/ · documents/[id]/ · documents/[id]/texts/[sha]/edit/ · …
  sign-in/
lib/api/                generated types (openapi-typescript) + one small typed fetch client, server-only
lib/session.ts          the token cookie (ADR-4)
components/             UI pieces: held list, document panels, text editor and diff, forms with field errors
e2e/                    Playwright: against the platform's API with a seeded test database
Dockerfile              Next.js standalone output
```

Its conventions:
- **TypeScript in strict mode.**
- **No database access and no business rules:** every decision comes from the API.
- **Forms** show each `422` field error beside its field, as the current app does.
- **The text editor** is CodeMirror, with the source's page markers (`<!-- page N -->`) protected and a side-by-side diff. That's the one place the new stack clearly improves on a plain text area.
- **Accessibility and wording** are carried over from the current templates: skip link, labels, live regions, the done notices.

## Migration plan

The current app keeps running and serving curators until the last step.

### Phase 1: the JSON API, in the platform repository (additive)

- `adapters/api/` (FastAPI): the endpoints above, `ApiServices`, the token, presigned URLs.
- `metamorph api` command; `api` compose service on its own port, from the same `metamorph-platform` image.
- `docs/api/openapi.json`, with a test that it matches the app.
- Tests, in the style of `test_web.py` and `test_web_postgres.py`:
  - with fakes: every endpoint, every error shape, and the token;
  - one database-and-S3 end-to-end run: sign in, correct a text, see it published.

**Done when:** every capability of the 23 HTML routes has an endpoint; the suite, lint and architecture test pass; the HTML app is untouched and still serving.

**Built, 2026-10-19.** 24 operations (9 reads, 14 actions, sign-in); 408 tests pass with PostgreSQL and S3; lint and the architecture test are clean; the HTML app is unchanged. What it added, all inside the existing layout:
- `adapters/api/app.py` (the endpoints, `ApiServices`, the error shapes), `tokens.py` (the session token), `openapi.py` (writes the contract);
- `S3FileLinks` in `adapters/blobs/s3.py` (presigned links, and reading an upload back);
- `METAMORPH_S3_PUBLIC_ENDPOINT_URL` (optional): links are signed for the address browsers use, which locally isn't the one the API uses (`objectstore:8333` vs `localhost:8333`);
- `metamorph api` (port 8001), the `api` compose service, and `docs/api/openapi.json`;
- tests: `test_api.py` (fakes), `test_api_tokens.py`, `test_api_contract.py`, `test_api_postgres.py` (PostgreSQL and S3, end to end), and S3 link tests. The fake read models moved from `test_web.py` to `tests/curation_samples.py`, so they outlive the HTML app's tests.

Small departures from the sections above:
- **The `FileLinks` port belongs to the API adapter**, not to `application/ports.py`: no use case needs links. It also reads an upload back (`uploaded`), so a missing upload simply arrives as no file, and `AddManualDocument` reports it beside `file` like any other field.
- **An upload key must be under `uploads/`**; any other key counts as no file, so a document can't be added from another document's stored file.
- **SeaweedFS ignores the file name a link asks for** (S3 honours it); the link still asks.
- **Uploaded objects stay under `uploads/` after their document is added** (the file is stored again, content-addressed, by the load). Give the bucket a lifecycle rule expiring `uploads/` after a day.

### Phase 2: the new repository's foundation

- Next.js, TypeScript strict, ESLint, the generated client.
- Sign-in and session; the layout and navigation; the overview page.
- CI: type check, lint, unit tests, and Playwright against the platform's compose stack (`postgres`, `objectstore`, `migrate`, `api`), with a seeded database.

**Done when:** a curator can sign in to the new app and see the overview, alongside the old app.

**Built, 2026-10-19,** in `../Metamorph-Curation-Web`:
- **Stack:** Next.js 16.4 (App Router, Cache Components), TypeScript strict, Tailwind v4, `openapi-fetch`.
- **Pages:** sign-in and the Overview.
- **Tests:** 21 unit tests (Vitest), and 3 Playwright end-to-end tests against a real API, in dev and in production builds.
- **Container:** the standalone image builds and serves.
- **The contract:** `npm run api:check` fails when `src/lib/api/schema.d.ts` drifts from `docs/api/openapi.json`.
- **CI:** `.github/workflows/ci.yml` runs the checks, then the end-to-end tests against this repository's compose `api` service. It needs a `PLATFORM_REPOSITORY` variable and the `PLATFORM_TOKEN`, `E2E_CURATORS`, `E2E_USERNAME` and `E2E_PASSWORD` secrets.

Notes from building it:
- **Every read is at request time.** With Next's Cache Components, a page's frame prerenders and anything that reads the session streams in behind `<Suspense>`. Curation reads call `connection()` first, so they are never prerendered or prefetched ahead: curation data is always live.
- **`src/proxy.ts` (Next 16's middleware) only checks that the session cookie exists.** The API judges whether it is valid on every read. An expired session goes back to sign-in, with a note.
- **The navigation lists only the pages rebuilt so far.** Each page joins it in Phase 3.
- **The visual identity is the first app's,** carried into Tailwind v4 tokens: deep-green accent, 6px radius, light and dark. The type is now Geist. The UI was reviewed against Vercel's Web Interface Guidelines, and its findings were fixed. It was checked in light and dark at desktop and phone widths.

### Phase 3: pages, in order of value

1. **Held list and the document page** (read-only).
2. **Approve as is; edit text with the protected editor and the diff.**
3. Field corrections, assigning an ID, suppressing and restoring, linking citations, conflicts.
4. The review queues.
5. Adding a document, with the upload going directly to S3.

Each page ships when its Playwright tests pass, and curators may use it while the old app still serves every page.

**Done when:** every page and action of the old app exists in the new one.

**Built, 2026-10-19.**
- **Pages:** held list, review queues, search, the document page with every action, the text editor and its changes page, and adding a document. The old app's wording and accessibility are carried over.
- **Tests:** 55 unit tests and 18 Playwright end-to-end tests, run on a production build against the real API. The end-to-end tests run in a world of their own: database `metamorph_e2e`, bucket `metamorph-e2e`, the API on port 8012, and a fresh seed for each spec file from a committed four-document bundle.
- **Reviews:** the UI was reviewed against Vercel's Web Interface Guidelines, and checked in light and dark at desktop and phone widths.

Notes from building it:
- **The text editor is CodeMirror 6,** loaded on its page only (`next/dynamic`). It refuses any change that touches a page marker line, its edges, or the line breaks around it; the API's own check stays the backstop. A 1.8 MB paged text (the longest held) opens in under a second, and an edit at its end saves. The changes are shown as the API's unified diff, coloured by line, rather than side by side: the API already computes it, so nothing heavier is needed.
- **Server-action request bodies are allowed up to 4 MB** (Next's default is 1 MB), because a text correction carries the whole text.
- **Browser uploads need the bucket's CORS rule.** `metamorph storage init` gained `--upload-origin URL` (repeatable, additive), which allows `PUT` from the web app's origin. SeaweedFS honours it, as S3 does.
- **A refused form keeps what the curator typed.** React resets a form after its action; `ActionForm` submits through a transition instead, so a refusal shows its reason beside the form with the entries intact.
- **`metamorph web`'s "Document added and published" notice** is now "Document added. It is published once it passes the publish gate." That is what happens under the gate.

### Phase 4: cut-over and retirement

1. **Point** the curation domain at the Next.js app.
2. **Once it is stable, at once and with no fallback period,** in one platform-repository change:
   - delete `adapters/web/` (except `accounts.py`, which moves to `adapters/api/`);
   - delete the `metamorph web` command and the `web` compose service;
   - delete `test_web.py` and `test_web_postgres.py` (`test_web_accounts.py` follows `accounts.py`);
   - update the README.

**Done when:** curators work only in the new app, the platform repository holds no HTML, and the full suite passes.

**Done, 2026-10-19.**
- **The cut-over:** the compose `web` service now builds Metamorph-Curation-Web from its repository and serves it at http://localhost:8000. It reaches the API on the compose network. The dev bucket allows uploads from that origin. Checked in a browser: the address serves the new console, and a sign-in reaches the API.
- **The retirement:**
  - `adapters/web/` is deleted, along with its templates and static files;
  - `accounts.py` moved to `adapters/api/` (a move, kept green), and its test moved with it;
  - the `metamorph web` command, `wiring.web_services` and `web_app`, `test_web.py` and `test_web_postgres.py` are deleted;
  - the `jinja2` and `python-multipart` dependencies are dropped.
- **Tests:** the platform suite passes (381 tests, after the 28 that only tested the old app). Lint and the architecture test are clean.

Departures from step 2:
- **The compose `web` service isn't deleted. It is the new app,** because the compose stack is where the curation address points locally.
- **`Settings.require_web()` is now `require_curation()`,** since only the API needs it. The environment variable keeps its name, `METAMORPH_WEB_SECRET`, so existing `.env` files and the compose file need no change.
- The old app remains in git history (commit `15b479b`).

## Deployment

| Piece | Locally | In production (see the deployment notes on RDS and S3) |
|---|---|---|
| API | `api` service in the platform's compose file | The platform image (`metamorph api`), private network only |
| Web app | `npm run dev` in the new repository, or its image, pointed at `http://localhost:<api port>` | Its own container behind the HTTPS load balancer: the only public surface |
| Configuration | `.env` | Secrets Manager: `METAMORPH_WEB_SECRET` for the API; the API's URL and the cookie settings for the web app |

The two deploy independently. A frontend change never redeploys the platform. A platform change redeploys the API, and the frontend only follows when the contract changes.

## Testing

| Layer | Where | What |
|---|---|---|
| Domain and use cases | Platform | Unchanged |
| API adapter | Platform | Endpoints with in-memory fakes; one end-to-end run with PostgreSQL and S3; the committed OpenAPI file matches |
| Architecture | Platform | `test_architecture.py`, unchanged: it already covers any adapter |
| Contract | Web app | Type check against the generated types: a breaking API change fails the build |
| UI | Web app | Unit tests for components; Playwright end to end against the real API and a seeded database |

## Risks

| Risk | Guard |
|---|---|
| The contract drifts between the two repositories | The committed OpenAPI file, the test that it matches, generated types, versioned paths |
| Sign-in becomes weaker than basic auth over a private network | Short-lived signed tokens, httpOnly Secure cookie, private API, HTTPS only. An identity provider later |
| Gaps while two apps run, such as an action that exists in only one | Both stay on the same API and the same database, so state never diverges. Cut-over only at full parity |
| Two stacks and two deployments to maintain | A thin, generated client. The frontend holds no business rules, so most changes touch one side only |
| Large texts in the browser editor | CodeMirror handles megabyte documents. Measure the largest text (1.8 MB) in Phase 3 before shipping the editor |

## Out of scope

- Changing the domain, use cases, pipeline, database schema or the `published` contract.
- Reorganizing the platform repository.
- An identity provider (prepared for by ADR-4, not part of this move).
- A public API, or clients other than the curation web app.

## Decisions taken (2026-10-19)

1. **Repository name:** `Metamorph-Curation-Web`.
2. **Hosting the web app:** in the same AWS network as the API. The API stays private (ADR-2).
3. **No fallback period:** the old app is deleted as soon as the new one is stable (Phase 4).
