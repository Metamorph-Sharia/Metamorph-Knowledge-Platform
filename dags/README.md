Airflow DAGs (Phase 6), mounted into the `airflow` service at /opt/airflow/dags.

| File | DAGs |
|---|---|
| `ingest.py` | The regulation layer: `ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa`, `ingest_dsn_fatwa_full`: collect and export → `metamorph load` → discard. The market data layer, weekly on Mondays: `ingest_ojk_register`, `ingest_ojk_stats`, `ingest_bi_seki`, `ingest_bps_stats`, `ingest_reports`: collect and export → `metamorph market load` → discard. The market DAGs run on the local stack only until the market layer joins AWS (their ECS task definitions are deferred) |
| `registry_build.py` | `registry_build` (after every regulation load) and `health` (daily, both layers) |
| `market_publish.py` | `market_publish` (after every market load): `metamorph market publish` |

**How the DAGs depend on each other.** A load's success updates its layer's registry, an Airflow [Dataset](https://airflow.apache.org/docs/apache-airflow/2.10.5/authoring-and-scheduling/datasets.html), and that triggers the DAG that publishes it. The URIs are in `metamorph_pipeline/jobs.py`. Airflow's **Browse → DAG Dependencies** and **Datasets** views draw this graph:

```
ingest_ojk, ingest_bpk, ingest_bi,                ─► metamorph://registry         ─► registry_build ─► metamorph://published
ingest_dsn_fatwa, ingest_dsn_fatwa_full               (`registry`)                                       (`published`)

ingest_ojk_register, ingest_ojk_stats,            ─► metamorph://market-registry  ─► market_publish ─► metamorph://published-market
ingest_bi_seki, ingest_bps_stats, ingest_reports      (`market`)                                         (`published_market`)
```

Market loads that land close together are published once: `market publish` rebuilds `published_market` whole from every record held. Nothing consumes the two `published` Datasets yet; the retrieval layer's indexer will.
| `metamorph_pipeline/jobs.py` | The jobs as plain data: images, commands, schedules, mounts. Tested in `tests/test_dag_jobs.py` without Airflow |
| `metamorph_pipeline/containers.py` | The one place that builds Airflow operators: every task is a container, through the host's Docker (the local stack) or as an ECS task (`METAMORPH_TASK_LAUNCHER=ecs`, [AWS](../docs/aws-deployment-guide.md)) |
| `metamorph_pipeline/alerts.py` | Failure alerts: the log, and `METAMORPH_ALERT_WEBHOOK_URL` when set |
