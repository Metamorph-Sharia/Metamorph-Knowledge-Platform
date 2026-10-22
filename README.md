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
| [docs/aws-step9-guide.md](docs/aws-step9-guide.md) | Running the plan's step 9 (MinerU re-extraction) on one AWS GPU instance in Jakarta, then the live rollout from its cached readings: design, costs, runbook with the AWS CLI |
| [docs/aws-step9-console-guide.md](docs/aws-step9-console-guide.md) | The same, step by step in the AWS web console |
| [docs/aws-step9-sagemaker-guide.md](docs/aws-step9-sagemaker-guide.md) | Step 9 with access to Amazon SageMaker AI only: an on-demand training job, set up from Studio and the console |
| [docs/aws-deployment-guide.md](docs/aws-deployment-guide.md) | Deploying the whole stack on AWS in Jakarta: every service its own ECS service (Fargate, and a GPU capacity provider for MinerU that runs only in the ingest window), RDS PostgreSQL, settings in Parameter Store, one CloudFormation stack per service ([`deploy/aws/`](deploy/aws)). Design, costs, then a step-by-step runbook |
| [docs/deployment-architecture.md](docs/deployment-architecture.md) | The architecture as deployed with MinerU: the rings in each package, the composition roots, the services, what changes at deployment, and why step 9 on SageMaker AI leaves it as it is |
| [docs/mineru-extraction-plan.md](docs/mineru-extraction-plan.md) | MinerU extraction in every connector, text cleaning, parser 6 (huruf/angka) and the retrieval units: architecture, steps, validation |
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

## Running MinerU

With `METAMORPH_PDF_ENGINE=mineru`, connectors send their PDFs to one MinerU service (`packages/metamorph-pdf-text`; design: [docs/mineru-extraction-plan.md](docs/mineru-extraction-plan.md)). It runs MinerU 4.0.12, the only version the reader accepts, started with `--tier standard`, which serves both tiers the connectors ask for. With the default, `pymupdf`, nothing calls it.

**On a Mac** it runs natively, because Docker on macOS has no GPU. The VLM runs on llama.cpp, the small models on torch.

```bash
uv tool install --python 3.12 "mineru[torch]==4.0.12"
mineru-kit models download --tier standard     # 2.1 GB into ~/.mineru/models; covers basic too
mineru-kit models verify --tier standard
docker/mineru/run-dev.sh                        # http://127.0.0.1:8010; connectors reach it at host.docker.internal:8010
```

To keep it running, install the launchd agent, which runs `run-dev.sh` at login and restarts it if it stops:

```bash
sed -e "s|@PLATFORM@|$PWD|g" -e "s|@HOME@|$HOME|g" docker/mineru/dev.mineru.plist \
    > ~/Library/LaunchAgents/dev.metamorph.mineru.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.metamorph.mineru.plist   # log: ~/Library/Logs/metamorph-mineru.log
launchctl bootout gui/$(id -u)/dev.metamorph.mineru                                   # to stop it
```

**In production** it is the compose service `mineru` (profile `mineru`): Linux, an NVIDIA GPU with at least 8 GB, and 16 GB of RAM. Its image (`docker/mineru/Dockerfile`) pins MinerU and holds its models, and the VLM runs on vLLM. Start it with `docker compose --profile mineru up -d mineru`, and give the connectors `METAMORPH_MINERU_URL=http://mineru:8010`.

**The API key** is `METAMORPH_MINERU_API_KEY` in `.env`: both `run-dev.sh` and the compose service start MinerU with it, and Airflow gives it to the connectors. Without a key, anything that can reach the port can use the service. That is only this Mac (`127.0.0.1`), or the compose network and the server's own loopback.

**Check it** before pointing connectors at it. The check confirms the version, the tiers, and that each tier's models read a page from its text and from its image. Any PDFs given are also timed per tier and mode:

```bash
uv run python packages/metamorph-pdf-text/scripts/mineru_check.py [PDF ...]   # METAMORPH_MINERU_URL, default :8010
```

Measured on this Mac (M5, 24 GB) on 2026-10-21, with BPK files of 43 and 50 pages:

| Tier | Born-digital: MinerU reads the PDF's characters | Scan: MinerU reads the page image | Born-digital, OCR forced |
|---|---|---|---|
| `basic` (annexes and other files) | 74 pages a minute | 28 | 32 |
| `standard` (main files) | 86 | 7.7 | 12 |

Scans and noisy text layers, which `request_for` forces to OCR, are the slow case. The rates include the reader's 5-second poll, so they are what a connector gets.

**Licenses:**
- **MinerU** is under the MinerU Open Source License (Apache 2.0 with conditions). A service offered to third parties must say visibly that it uses MinerU. The curation console's footer does ("Text extraction by MinerU").
- **Its models** are Apache 2.0: `opendatalab/MinerU-4_models_torch` and `opendatalab/MinerU2.5-Pro-2605-1.2B`, which production runs.
- **The Mac's VLM** comes from `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`, a third party's GGUF conversion of that model. Its card states no license, so it is for development only.

## Curate

The Metamorph team's console is **[Metamorph-Curation-Web](../Metamorph-Curation-Web)** (Next.js and TypeScript), in its own repository. The compose `web` service builds it from there and serves it at http://localhost:8000 (`docker compose up -d web`). It calls the platform only through the **curation JSON API**.

**The curation JSON API** is `metamorph api` (`adapters/api/`; `docker compose up -d api`, at http://localhost:8001/api/v1):
- **Reads:** the overview, the held list, the review queues, search (documents by metadata or published wording, and the matching articles, with filters), browsing by series, a document's full view, a text read as the parser cut it (laid out for reading: printed lines joined into paragraphs and list items, page furniture dropped, `domain/layout.py`), a text to edit, a correction's changes, and file links.
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
