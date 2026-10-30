"""Refresh the market index whenever published_market is republished: the retrieval layer's DAG, in its own image.

market_index   `scripts/refresh-market-index.sh` in the retrieval image (Metamorph-Retrieval): a new version of the
               index of the market's report and release passages and dataset cards, judged against the active one on
               the market question set, and activated only if no worse; updates `market-index`

A version judged worse is kept, inactive, and the task fails, so the alert says so; the active version keeps
answering. Embedding models are kept in the `metamorph-models` volume between runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container
from metamorph_pipeline.jobs import MARKET_INDEX, MODELS, MODELS_VOLUME, PUBLISHED_MARKET, RETRIEVAL_IMAGE, Mount

DEFAULT_ARGS = {"retries": 0, "on_failure_callback": on_failure}  # a worse version stays worse on a retry

with DAG(
    dag_id="market_index",
    description="index published_market for retrieval; activate the new version only if no worse",
    schedule=[Dataset(PUBLISHED_MARKET)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["market", "retrieval"],
) as market_index:
    container("refresh", RETRIEVAL_IMAGE, ["scripts/refresh-market-index.sh"],
              mounts=[Mount(MODELS_VOLUME, MODELS, kind="volume")], secrets=["METAMORPH_DATABASE_URL"],
              execution_timeout=timedelta(hours=1), outlets=[Dataset(MARKET_INDEX)])
