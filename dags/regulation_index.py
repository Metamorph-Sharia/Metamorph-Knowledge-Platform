"""Refresh the regulation index whenever published is republished: build a snapshot, judge it, activate if no worse.

regulation_index   `scripts/refresh-regulation-index.sh` in the retrieval image (Metamorph-Retrieval): a new snapshot of
                   chunks, document metadata, bge-m3 vectors and links, judged against the live snapshot with
                   metamorph-eval on the regulation question sets, as market_index judges its versions, and activated
                   only if no worse; updates `regulation-index`

A snapshot judged worse is kept, inactive, and the task fails, so the alert says so; the active one keeps answering.
The build is a full rebuild and the swap is one transaction, so a failed run leaves the previous snapshot live.
Embedding models are kept in the `metamorph-models` volume between runs.

A build takes the live snapshot's vectors by chunk id, as market_index reuses its embedding cache, so a refresh embeds
only the chunks a publish added or changed. bge-m3 embeds about 1.6 chunks/second on 2 vCPU, so a first build, or one
after a change to what the model reads, would take about 100 hours there: seed it with vectors exported from a build
made where embedding is fast (Metamorph-Retrieval docs/deploying.md). The 24h timeout below is a guard, not a target.
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
        execution_timeout=timedelta(hours=24),  # a guard: a refresh embeds only what a publish changed
        outlets=[Dataset(REGULATION_INDEX)],
    )
