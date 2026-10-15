"""One DAG per connector job (metamorph_pipeline/jobs.py): collect and export → load → discard the bundle.

A successful load updates the `registry` Dataset, which triggers registry_build.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.utils.trigger_rule import TriggerRule
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container, platform
from metamorph_pipeline.jobs import (
    BUNDLES,
    BUNDLES_VOLUME,
    Mount,
    bundle_path,
    collect_command,
    discard_command,
    ingest_jobs,
)

REGISTRY = Dataset("metamorph://registry")
RUN_ID = "{{ ts_nodash }}"
DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=15), "on_failure_callback": on_failure}


def _setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set: see Metamorph-Knowledge-Platform/.env.example")
    return value


for job in ingest_jobs(_setting("METAMORPH_WORKSPACE"), ojk_credentials=_setting("METAMORPH_OJK_CREDENTIALS")):
    with DAG(
        dag_id=job.dag_id,
        description=job.description,
        schedule=job.schedule,
        start_date=datetime(2026, 10, 1),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["ingest", *job.tags],
    ) as dag:
        collect = container(
            "collect", job.image, collect_command(job, RUN_ID), mounts=job.mounts, secrets=job.secrets,
            execution_timeout=timedelta(hours=6),
        )  # fmt: skip
        load = platform(
            "load", ["load", bundle_path(job.connector, RUN_ID)],
            mounts=[Mount(BUNDLES_VOLUME, BUNDLES, kind="volume")],
            trigger_rule=TriggerRule.ALL_DONE,  # a run that raised alerts still exported its bundle
            outlets=[REGISTRY],
        )  # fmt: skip
        discard = container("discard", job.image, discard_command(job, RUN_ID), mounts=job.mounts, retries=0)
        collect >> load >> discard
    globals()[job.dag_id] = dag
