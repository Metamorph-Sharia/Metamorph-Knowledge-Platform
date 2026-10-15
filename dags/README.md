Airflow DAGs (Phase 6), mounted into the `airflow` service at /opt/airflow/dags.

| File | DAGs |
|---|---|
| `ingest.py` | `ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa`, `ingest_dsn_fatwa_full`: collect and export → load → discard |
| `registry_build.py` | `registry_build` (after every load) and `health` (daily) |
| `metamorph_pipeline/jobs.py` | The jobs as plain data: images, commands, schedules, mounts. Tested in `tests/test_dag_jobs.py` without Airflow |
| `metamorph_pipeline/containers.py` | The one place that builds Airflow operators: every task is a container |
| `metamorph_pipeline/alerts.py` | Failure alerts: the log, and `METAMORPH_ALERT_WEBHOOK_URL` when set |
