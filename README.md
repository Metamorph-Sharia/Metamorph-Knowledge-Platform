# Metamorph Knowledge Platform

The **Data/Source Management layer** of Metamorph's legal knowledge base for the sharia market-entry assistant. It takes what the source connectors collect (OJK, BI, BPK, DSN-MUI; each in its own repository) and builds one PostgreSQL database that the Knowledge and Retrieval layer reads.

> **Status (2026-10-14):** Phases 1–2 done: contract v2 and the platform skeleton (local stack, PostgreSQL schemas). Next: Phase 3, the OJK export, loader and publish. Plan: [docs/data-source-management-plan.md](docs/data-source-management-plan.md).

## Layout

| Path | What it is |
|---|---|
| [packages/metamorph-contract](packages/metamorph-contract/CONTRACT_V2.md) | **Contract v2**: JSON Schemas (the formal contract) for the normalized document and bundle manifest, the matching Python types, validator and bundle writer/reader. Every connector depends on it |
| [src/metamorph_platform](src/metamorph_platform) | The platform: `metamorph` CLI, PostgreSQL migrations (`adapters/postgres/migrations`). Layers follow the dependency rule, enforced by `tests/test_architecture.py` |
| [compose.yaml](compose.yaml) | Local stack: PostgreSQL 16 + pgvector, SeaweedFS (S3), Airflow 2.10, and the platform image |
| [docs/data-source-management-plan.md](docs/data-source-management-plan.md) | The phased plan for this layer |

## The database

| Schema | Holds | Written by |
|---|---|---|
| `ingest` | Runs, bundles received, quarantined lines, events | Airflow tasks, the loader |
| `registry` | The system of record: documents merged across sources, files, text versions, provisions, citations, links, status history | The loader, resolver and parser only |
| `curation` | The Metamorph team's overrides, suppressions, review queue, conflicts, audit log | The curation web app only |
| `published` | **The read contract for the Knowledge and Retrieval layer:** effective values, public content, `change_log` for incremental indexing | The publish step only |

## Run the stack

```bash
docker compose up -d --build     # postgres :5433 · S3 :8333 · Airflow :8080; `migrate` applies the schema, then exits
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt   # Airflow login: admin / this
docker compose down              # keep data; add -v to wipe it
```

## Develop

```bash
uv sync                          # the workspace: platform, contract package, dev tools
uv run pytest                    # offline tests; database tests are skipped
METAMORPH_TEST_DATABASE_URL=postgresql://metamorph:metamorph-dev@localhost:5433/postgres uv run pytest
                                 # + database tests, each in a throwaway database on the compose server
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
