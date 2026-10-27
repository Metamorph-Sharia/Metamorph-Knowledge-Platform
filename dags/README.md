Airflow DAGs (Phase 6), mounted into the `airflow` service at /opt/airflow/dags.

| File | DAGs |
|---|---|
| `ingest.py` | `ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa`, `ingest_dsn_fatwa_full`: collect and export → `metamorph load` → discard. `ingest_ojk_register` (Mondays 02:45 UTC, the market data layer): `ojk-register sync` and export → `metamorph market load --publish` → discard. It runs on the local stack only until the market layer joins AWS (its ECS task definition is deferred) |
| `registry_build.py` | `registry_build` (after every load) and `health` (daily) |
| `metamorph_pipeline/jobs.py` | The jobs as plain data: images, commands, schedules, mounts. Tested in `tests/test_dag_jobs.py` without Airflow |
| `metamorph_pipeline/containers.py` | The one place that builds Airflow operators: every task is a container, through the host's Docker (the local stack) or as an ECS task (`METAMORPH_TASK_LAUNCHER=ecs`, [AWS](../docs/aws-deployment-guide.md)) |
| `metamorph_pipeline/alerts.py` | Failure alerts: the log, and `METAMORPH_ALERT_WEBHOOK_URL` when set |
