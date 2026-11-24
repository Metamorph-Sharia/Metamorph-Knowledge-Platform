"""Load what collection uploaded: one task per connector, every 30 minutes (ADR 0001, processing side).

load_bundles   `metamorph load-pending s3://<bundles bucket>/bundles/<connector>` in the platform image: the connector's
               complete bundles not yet loaded, oldest first, stopping at the first that fails or is incomplete. A held
               bundle fails only its own connector's task; the others go on. A task that loaded something succeeds and
               updates its layer's registry (`registry` or `market-registry`), which triggers registry_build or
               market_publish as before; one that found nothing to load is skipped, so no build runs for nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from metamorph_pipeline.alerts import on_first_failure
from metamorph_pipeline.containers import host_path, platform, required_setting
from metamorph_pipeline.jobs import LOAD_BUNDLES_SCHEDULE, NOTHING_LOADED, ingest_jobs, pending_loads
from metamorph_pipeline.sides import Side, builds_here

DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=10), "on_failure_callback": on_first_failure}

SIDE = Side.PROCESSING

if builds_here(SIDE):
    jobs = ingest_jobs(host_path("METAMORPH_WORKSPACE"), ojk_credentials=host_path("METAMORPH_OJK_CREDENTIALS"))
    with DAG(
        dag_id="load_bundles",
        description="load the bundles collection uploaded, per connector, oldest first",
        schedule=LOAD_BUNDLES_SCHEDULE,
        start_date=datetime(2026, 10, 1),
        catchup=False,
        max_active_runs=1,  # two passes would race for the same bundles
        default_args=DEFAULT_ARGS,
        tags=["load", "registry"],
    ) as load_bundles:
        for load in pending_loads(jobs, required_setting("METAMORPH_BUNDLES_BUCKET")):
            platform(
                load.task_id, load.command,
                execution_timeout=timedelta(hours=2),
                outlets=[Dataset(load.registry)],
                skip_on_exit_code=NOTHING_LOADED,  # a pass that loaded nothing is skipped: its Dataset does not fire
            )  # fmt: skip
