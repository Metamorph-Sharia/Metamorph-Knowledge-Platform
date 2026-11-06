"""Refresh the regulation index whenever published is republished: build a snapshot, judge it, activate if no worse.

regulation_index   `scripts/refresh-regulation-index.sh` in the retrieval image: chunks, document metadata, bge-m3
                   vectors and the index into staging tables, judged against the active snapshot on the acceptance
                   set, and activated only if no worse; updates `regulation-index`

A snapshot judged worse is kept, inactive, and the task fails, so the alert says so; the active one keeps answering.
The build is a full rebuild and the swap is one transaction, so a failed run leaves the previous snapshot live.
Embedding models are kept in the `metamorph-models` volume between runs.

Sizing matters: bge-m3 embeds about 1.6 chunks/second on 2 vCPU, so a full 577k build is ~100 hours there. This task
needs a larger or GPU-backed shape before it can own the schedule; until then, builds are run by hand and the index is
shipped as a dump. The 24h timeout below is a guard, not a target.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container
from metamorph_pipeline.jobs import (
    MODELS,
    MODELS_VOLUME,
    PUBLISHED,
    REGULATION_INDEX,
    RETRIEVAL_IMAGE,
    Mount,
)

DEFAULT_ARGS = {"retries": 0, "on_failure_callback": on_failure}  # a worse snapshots stays worse on a retry

with DAG(
    dag_id="regulation_index",
    description="index published for retrieval; activate the new snapshot only if no worse",
    schedule=[Dataset(PUBLISHED)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["regulation", "retrieval"],
) as regulation_index:
    container(
        "refresh",
        RETRIEVAL_IMAGE,
        ["scripts/refresh-regulation-index.sh"],
        mounts=[Mount(MODELS_VOLUME, MODELS, kind="volume")],
        secrets=["METAMORPH_DATABASE_URL"],
        execution_timeout=timedelta(hours=24),  # a guard, not a target: the build needs a bigger task
        outlets=[Dataset(REGULATION_INDEX)],
    )
