"""One DAG per connector job (metamorph_pipeline/jobs.py), on the collection host: collect and export, upload, discard.

The upload sends the bundle to the blobs bucket, marked complete; AWS loads it from there (docs/adr/0001). A failed
upload (the SSO session expired) keeps the bundle: sign in again and clear the upload task.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import ShortCircuitOperator
from airflow.utils.trigger_rule import TriggerRule
from metamorph_pipeline.alerts import on_failure
from metamorph_pipeline.containers import container, host_path, required_setting, upload_bundle
from metamorph_pipeline.jobs import (
    RUN_ID_TEMPLATE as RUN_ID,
)
from metamorph_pipeline.jobs import (
    collect_command,
    discard_command,
    ingest_jobs,
    monthly_pass_due,
    passed_on,
    upload_command,
)
from metamorph_pipeline.sides import Side, builds_here

SINCE = "{{ prev_start_date_success.isoformat() if prev_start_date_success else '' }}"  # a failed run widens it
DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=15), "on_failure_callback": on_failure}


SIDE = Side.COLLECTION


def _runs_today(data_interval_end, dag_run, prev_start_date_success, **_) -> bool:
    """A monthly job's schedule fires every weekday (`monthly`); it runs when none has succeeded this month. A run
    that this check skipped counts as a success only after one that ran did, so it never hides a missed month. A run
    triggered by hand always goes ahead."""
    return dag_run.external_trigger or monthly_pass_due(data_interval_end.date(), prev_start_date_success)


if builds_here(SIDE):
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
                "collect", job.image, collect_command(job, RUN_ID, SINCE), mounts=job.mounts, secrets=passed_on(job),
                execution_timeout=timedelta(hours=6),
            )  # fmt: skip
            upload = upload_bundle(
                "upload", upload_command(job, RUN_ID, required_setting("METAMORPH_BUNDLES_BUCKET")),
                trigger_rule=TriggerRule.ALL_DONE,  # a run that raised alerts still exported its bundle
            )  # fmt: skip
            discard = container("discard", job.image, discard_command(job, RUN_ID), mounts=job.mounts, retries=0)
            collect >> upload >> discard
            if job.monthly:
                today = ShortCircuitOperator(task_id="monthly_pass_due", python_callable=_runs_today)
                today >> collect
        globals()[job.dag_id] = dag
