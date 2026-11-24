"""The weekly backup of the connectors' data: each connector's data/ as a tarball in the ops bucket.

backup_connector_data   a task in the platform image (metamorph_pipeline/jobs.py: backup_command) packs every
                        connector's data directory, mounted from the collection host's disk, to
                        `s3://<ops bucket>/backups/<date>/<connector>.tgz`; the bucket expires them after 35 days.
                        A SQLite store goes in as a snapshot (a late ingest may still be writing), not as a live file

It runs on the collection host, under the Docker launcher, as the owner's SSO session (the same one the upload uses).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container, host_path, required_setting, sso_session
from metamorph_pipeline.jobs import backup_command, backup_job, backup_mounts, ingest_jobs
from metamorph_pipeline.sides import Side, builds_here

DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=15), "on_failure_callback": on_failure}
DATE = "{{ data_interval_end | ds }}"  # the day it runs; `ds` would be the Friday a week before

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
        jobs = ingest_jobs(host_path("METAMORPH_WORKSPACE"), ojk_credentials=host_path("METAMORPH_OJK_CREDENTIALS"))
        session_mounts, session = sso_session()
        container(
            "backup", job.image, backup_command(jobs, DATE),
            mounts=[*backup_mounts(jobs), *session_mounts],
            environment={**session, "OPS_BUCKET": required_setting("METAMORPH_OPS_BUCKET")},
            entrypoint=["sh", "-c"],  # the platform image's own is `metamorph`
            execution_timeout=timedelta(hours=2),
        )  # fmt: skip
