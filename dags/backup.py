"""The weekly backup of the connectors' data: each connector's data/ as a tarball in the ops bucket.

backup_connector_data   the ops task (metamorph_pipeline/jobs.py: backup_command) packs every connector's data directory from
                        EFS to `s3://<ops bucket>/backups/<date>/<connector>.tgz`; the bucket expires them after 35 days.
                        A SQLite store goes in as a snapshot (the daily ingests run on Sundays too), not as a live file

It runs as an ECS task: the scheduler role on AWS may only start and stop EC2, so EventBridge cannot run it. On the local
Docker stack there is no EFS to copy, so the DAG skips its task.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import ShortCircuitOperator
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import LAUNCHER, container, host_path
from metamorph_pipeline.jobs import backup_command, backup_job, ingest_jobs
from metamorph_pipeline.sides import Side, builds_here

DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=15), "on_failure_callback": on_failure}
DATE = "{{ data_interval_end | ds }}"  # the day it runs; `ds` would be the Sunday a week before

SIDE = Side.COLLECTION

if builds_here(SIDE):
    job = backup_job()
    with DAG(
        dag_id=job.dag_id,
        description=job.description,
        schedule=job.schedule,
        start_date=datetime(2026, 10, 1),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["ops", "backup"],
    ) as backup:
        if LAUNCHER == "ecs":
            jobs = ingest_jobs(host_path("METAMORPH_WORKSPACE"), ojk_credentials=host_path("METAMORPH_OJK_CREDENTIALS"))
            container("backup", job.image, backup_command(jobs, DATE), execution_timeout=timedelta(hours=2))
        else:
            ShortCircuitOperator(task_id="backup", python_callable=lambda: False)  # nothing on EFS: skipped, not failed
