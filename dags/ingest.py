"""One DAG per connector job (metamorph_pipeline/jobs.py): collect and export → load → discard the bundle.

A successful regulation load updates the `registry` Dataset, which triggers registry_build. A market load
publishes its own layer (`metamorph market load --publish`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.utils.trigger_rule import TriggerRule
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container, host_path, platform
from metamorph_pipeline.jobs import (
    BUNDLES,
    BUNDLES_VOLUME,
    Layer,
    Mount,
    collect_command,
    discard_command,
    ingest_jobs,
    load_command,
    passed_on,
)

REGISTRY = Dataset("metamorph://registry")
RUN_ID = "{{ ts_nodash }}"
DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=15), "on_failure_callback": on_failure}


for job in ingest_jobs(host_path("METAMORPH_WORKSPACE"), ojk_credentials=host_path("METAMORPH_OJK_CREDENTIALS")):
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
            "collect", job.image, collect_command(job, RUN_ID), mounts=job.mounts, secrets=passed_on(job),
            execution_timeout=timedelta(hours=6),
        )  # fmt: skip
        load = platform(
            "load", load_command(job, RUN_ID),
            mounts=[Mount(BUNDLES_VOLUME, BUNDLES, kind="volume")],
            trigger_rule=TriggerRule.ALL_DONE,  # a run that raised alerts still exported its bundle
            outlets=[REGISTRY] if job.layer is Layer.REGULATION else [],
        )  # fmt: skip
        discard = container("discard", job.image, discard_command(job, RUN_ID), mounts=job.mounts, retries=0)
        collect >> load >> discard
    globals()[job.dag_id] = dag
