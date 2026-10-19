# Metamorph Knowledge Platform

The **Data/Source Management layer** of Metamorph's legal knowledge base for the sharia market-entry assistant. It takes what the source connectors collect (OJK, BI, BPK, DSN-MUI; each in its own repository) and builds one PostgreSQL database that the Knowledge and Retrieval layer reads.

> **Status (2026-10-15):** All seven phases are built: contract v2, the platform, all four connectors loading and publishing (2,524 documents), the registry build, Airflow, and the curation app. The ingest DAGs ship paused. Plan: [docs/data-source-management-plan.md](docs/data-source-management-plan.md). The Knowledge and Retrieval layer's contract: [docs/published-schema.md](docs/published-schema.md).

## Layout

| Path | What it is |
|---|---|
| [packages/metamorph-contract](packages/metamorph-contract/CONTRACT_V2.md) | **Contract v2**: JSON Schemas (the formal contract) for the normalized document and bundle manifest, the matching Python types, validator and bundle writer/reader. Every connector depends on it |
| [src/metamorph_platform](src/metamorph_platform) | The platform: `metamorph` CLI, PostgreSQL migrations (`adapters/postgres/migrations`). Layers follow the dependency rule, enforced by `tests/test_architecture.py` |
| [compose.yaml](compose.yaml) | Local stack: PostgreSQL 16 + pgvector, SeaweedFS (S3), Airflow 2.10, and the platform image |
| [docs/data-source-management-plan.md](docs/data-source-management-plan.md) | The phased plan for this layer |
| [dags](dags/README.md) | Airflow DAGs: one ingest DAG per connector job, `registry_build`, `health` |
| [docs/published-schema.md](docs/published-schema.md) | **The read contract** for the Knowledge and Retrieval layer: tables, IDs, provision addresses, links, validity |
| [docs/curation-workflow-design.md](docs/curation-workflow-design.md) | The publish gate, held documents, approving as is, and text correction |
| [docs/curation-workflow-implementation-plan.md](docs/curation-workflow-implementation-plan.md) | How that design is built: two releases, step by step, test lists first |
| [docs/curation-web-separation-design.md](docs/curation-web-separation-design.md) | The curation web app in its own repository (Next.js + TypeScript) over the curation JSON API; migration plan (Phases 1 to 3 built) |

## The database

| Schema | Holds | Written by |
|---|---|---|
| `ingest` | Runs, bundles received, quarantined lines, events | Airflow tasks, the loader |
| `registry` | The system of record: documents merged across sources, files, text versions, provisions, citations, links, status history; and `hold`, the documents the publish gate holds back | The loader, resolver and parser; the publish step writes `hold` |
| `curation` | The Metamorph team's overrides, approvals, text corrections, suppressions, review queue, conflicts, audit log | The curation web app only |
| `published` | **The read contract for the Knowledge and Retrieval layer:** effective values, public content, `change_log` for incremental indexing. Only documents that pass the publish gate | The publish step only |

## Run the stack

```bash
docker compose up -d --build     # postgres :5433 · S3 :8333 · Airflow :8080; `migrate` applies the schema, then exits
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt   # Airflow login: admin / this
docker compose down              # keep data; add -v to wipe it
```

## Load a connector's bundle

```bash
cp .env.example .env                                    # dev settings for the compose stack
uv run --env-file .env metamorph storage init           # once: create the blob bucket (add --upload-origin URL
                                                        # for each curation web app origin that uploads files)
uv run --env-file .env metamorph load PATH/TO/BUNDLE --publish
uv run --env-file .env metamorph publish [--all]        # refresh `published` (e.g. after curation)
```

## Build the registry

```bash
uv run --env-file .env metamorph build        # parse → resolve → settle reviews → validity → publish; run it after loading
```

| Step | Command | What it does |
|---|---|---|
| Parse | `metamorph parse [--all]` | Each new or changed main text becomes a provision tree (`domain/structure/`) with citations found in the text (`domain/citations.py`) and the dates it states (`domain/dates.py`). A text whose structure fails the quality checks is stored with its problems, for the publish gate |
| Resolve | `metamorph resolve` | Citations become links when their target is held. A target not held yet waits and links once its connector loads it |
| Settle reviews | `metamorph settle` | Unlinked-citation items whose cause has gone are resolved by the platform (`metamorph-platform`), each with its reason and an audit row: the citation is now linked, no longer made, or read as naming a document. The rest are counted as needing a person. Conflicts and quarantined lines always wait for a person |
| Validity | `metamorph validity` | Amending and revoking links become status events and article end dates (`valid_to`) |
| Publish | `metamorph publish` | Refreshes `published` for every document any step changed, through the **publish gate** (`domain/gate.py`): a document is published only when its ID is canonical, it has a main text, today's parser read it, and its structure has no problems (or a curator approved them as they are). A document that fails is **held**: its last good version, if any, stays published, and its reasons go to `registry.hold`. The report counts `held` |

Each step only does what is new, so a second `build` changes nothing.

`load` refuses a connector run it has loaded before (a failed one may be retried). Lines that break the contract are quarantined in `ingest.quarantine`, and the rest still loads. Quarantined lines and conflicts are queued in `curation.review_item`; a document the connector couldn't identify is held by the publish gate until a curator assigns its ID.

## Run on a schedule (Airflow)

Airflow only schedules. Every task is a container: a connector's own image collects and exports a bundle into the `metamorph-bundles` volume, then the platform image loads it. Each load triggers `registry_build` (`metamorph build`, then `metamorph health`).

| DAG | When | What |
|---|---|---|
| `ingest_ojk` | daily 01:00 UTC | `ojk-connector run`, then `export --format v2` |
| `ingest_bpk` | daily 02:00 | `bpk-connector run`, then `export --format v2` |
| `ingest_bi` | daily 03:00 | `src.cli sync` into BI's own database, then `src.pipeline.exporter_v2` |
| `ingest_dsn_fatwa` | Mondays 04:00 | `dsn sync`, Arabic OCR, `dsn export` |
| `ingest_dsn_fatwa_full` | 1st of the month | the same, re-downloading every file |
| `registry_build` | after any load | `metamorph build`, then `metamorph health --fail-on critical` |
| `health` | daily 06:00 | `metamorph health --fail-on critical`: a connector that stopped loading never triggers a build |

A run that raises alerts still exports and loads its snapshot. The collect task fails only at the connector's error exit code. The bundle is removed once it is loaded, and kept when the load fails. Failures go to the task log, and to `METAMORPH_ALERT_WEBHOOK_URL` when set.

Setup, once:

```bash
cp .env.example .env               # set METAMORPH_WORKSPACE: the directory holding every repository
docker compose --profile connectors build                # the platform image and the four connector images
docker compose up -d                                     # Airflow at :8080
docker compose exec postgres sh /docker-entrypoint-initdb.d/02-bi.sh   # only on a volume created before Phase 6
```

- **Connector state:** each connector keeps its state in its own repository's `data/` directory, bind-mounted. A scheduled run and a person's CLI run share one store, so don't run both at once.
- **OJK's RegAlert token:** it is mounted from `METAMORPH_OJK_CREDENTIALS` (default `~/.config/ojk-connector/credentials`). Sign in once with `uv run ojk-connector auth login regalert` in the OJK repository.
- **BI's database:** BI's pipeline writes to `bi`, a database of its own in this PostgreSQL. Its first run ingests BI's newest regulations into it.
- **Code changes:** images contain their code. After changing a connector, rebuild with `docker compose --profile connectors build <name>-connector`.
- **Starting:** the DAGs ship paused. To try one without scheduling it, run `docker compose exec airflow airflow dags test ingest_dsn_fatwa`. To run unattended, unpause the DAGs in the UI, or with `airflow dags unpause <dag_id>`.

## Curate

The Metamorph team's console is **[Metamorph-Curation-Web](../Metamorph-Curation-Web)** (Next.js and TypeScript), in its own repository. The compose `web` service builds it from there and serves it at http://localhost:8000 (`docker compose up -d web`). It calls the platform only through the **curation JSON API**.

**The curation JSON API** is `metamorph api` (`adapters/api/`; `docker compose up -d api`, at http://localhost:8001/api/v1):
- **Reads:** the overview, the held list, the review queues, search, a document's full view, a text to edit, a correction's changes, and file links.
- **Actions:** correcting and withdrawing fields; approving a text's problems as they are; correcting a text's wording and withdrawing it; suppressing and restoring; assigning an ID; linking citations; deciding conflicts and review items; adding a document. Each action calls exactly one curation use case, then parses, publishes and re-checks the publish gate before it answers.
- **Sign-in:** `POST /api/v1/auth/session` returns a short-lived session token (ADR-4).
- **Files:** they move through short-lived S3 links. The bucket must let the web app's origin upload: `metamorph storage init --upload-origin URL`.
- **The contract** is [docs/api/openapi.json](docs/api/openapi.json). A test keeps it in step with the code; regenerate it with `uv run python -m metamorph_platform.adapters.api.openapi`. Design and history: [docs/curation-web-separation-design.md](docs/curation-web-separation-design.md).

Every action needs a reason. It is written to `curation.audit_log` in the same transaction as the change.

**Behaviour:**
- **Corrections are overlays:** a reload never undoes one. A source that later changes a corrected field raises a conflict.
- **File access:** a file opens through a short-lived link the API signs. The object store stays private otherwise.

**Accounts:** team accounts come from `METAMORPH_CURATORS`, a JSON list of `{username, name, password_hash}` (see `.env.example`). Make a hash with `uv run metamorph curator hash-password`. Set `METAMORPH_WEB_SECRET`, which signs the session tokens, to `openssl rand -hex 32`. Without them, `metamorph api` refuses to start and says why.

## Develop

```bash
uv sync                          # the workspace: platform, contract package, dev tools
uv run pytest                    # offline tests; database tests are skipped
uv run --env-file .env.example env METAMORPH_TEST_DATABASE_URL=postgresql://metamorph:metamorph-dev@localhost:5433/postgres \
    METAMORPH_TEST_S3_ENDPOINT_URL=http://localhost:8333 pytest
                                 # + database tests (a throwaway database each) and S3 tests (a throwaway bucket each)
uv run ruff check src tests packages
cp .env.example .env             # then: uv run --env-file .env metamorph db status
```

## Using the contract from a connector

Until it is published, connectors depend on it by path (a git tag later):

```toml
# a connector's pyproject.toml
dependencies = ["metamorph-contract"]

[tool.uv.sources]
metamorph-contract = { path = "../Metamorph-Knowledge-Platform/packages/metamorph-contract" }
```
