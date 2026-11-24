# 01 The side switch: each Airflow loads only its side's DAGs

Status: ready-for-agent
Blocked by: none
Spec: ../spec.md ("Two sides, one registry"); ADR: docs/adr/0001-collection-on-a-residential-host.md; vocabulary: GLOSSARY.md

## What

A setting `METAMORPH_SIDE` (`collection` | `processing`) decides which DAGs an Airflow builds. One `dags/` folder and one job registry serve both.

- Collection side: the ingest DAGs and `backup_connector_data`.
- Processing side: `registry_build`, `health`, `market_publish`, `market_index`, `regulation_index` (and later `load_bundles`, ticket 05).
- Missing or unknown value: importing the DAGs fails with a message naming the setting and its two values (like the existing `METAMORPH_TASK_LAUNCHER` check).
- Each DAG module declares its side in one obvious place; the rule that decides "does this DAG build here" lives in the pipeline package, testable without Airflow.
- The local Compose Airflow sets `collection`; the AWS Airflow task definition sets `processing`.

## Acceptance

- Plain-data tests (prior art: tests/test_dag_jobs.py) show which DAG ids each side builds and that a missing/unknown side fails clearly.
- The AWS Airflow template sets `processing` (checked in tests/test_ingestion_stacks.py); compose sets `collection`.
- Full suite passes.
