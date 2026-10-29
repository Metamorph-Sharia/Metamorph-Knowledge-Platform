"""Build the registry whenever a connector's bundle is loaded, and check health every day regardless.

registry_build   parse → resolve → validity → publish (`metamorph build`), then health; updates `published`
health           a connector that stops loading never triggers a build, so health also runs on a clock
Both fail only on critical health (`--fail-on critical`); warnings are in ingest.health_snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import platform
from metamorph_pipeline.jobs import PUBLISHED, REGISTRY

DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=10), "on_failure_callback": on_failure}
HEALTH = ["health", "--fail-on", "critical"]

with DAG(
    dag_id="registry_build",
    description="parse, resolve, validity, publish; then health",
    schedule=[Dataset(REGISTRY)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["registry"],
) as registry_build:
    build = platform("build", ["build"], execution_timeout=timedelta(hours=2), outlets=[Dataset(PUBLISHED)])
    build >> platform("health", HEALTH)

with DAG(
    dag_id="health",
    description="is ingestion healthy? fails on critical",
    schedule="0 6 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["registry"],
) as health:
    platform("health", HEALTH)
