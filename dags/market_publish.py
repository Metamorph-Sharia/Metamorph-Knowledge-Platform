"""Publish the market layer whenever a market connector's bundle is loaded: the Market Registry's own DAG.

market_publish   `metamorph market publish`: published_market rebuilt whole from the market registry (`market`), in
                 one transaction; updates `published-market`, the layer's read contract

Loads that land close together are published once: a rebuild reads every record held, so one run covers them all.
Health is checked by the daily `health` DAG, which covers both layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import platform
from metamorph_pipeline.jobs import MARKET_REGISTRY, PUBLISHED_MARKET

DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=10), "on_failure_callback": on_failure}

with DAG(
    dag_id="market_publish",
    description="rebuild published_market from the market registry",
    schedule=[Dataset(MARKET_REGISTRY)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["market", "registry"],
) as market_publish:
    platform("publish", ["market", "publish"], execution_timeout=timedelta(hours=1),
             outlets=[Dataset(PUBLISHED_MARKET)])
