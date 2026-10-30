# The ingestion layer: Airflow, the connectors and MinerU on ECS

> **Superseded, 2026-10-30:** [docs/aws-deployment-plan.md](../../../docs/aws-deployment-plan.md) revises this layer (nine connectors, RDS, a private VPC, MinerU's window matched to the DAGs). The templates here are its starting point.

**Status:** designed, linted (`cfn-lint`, CloudFormation's `validate-template`) and tested against the core's exports (`tests/test_deploy_layers.py`); not deployable with the account's access as of 2026-10-23. **Deploy the core first:** [docs/aws-deployment-guide.md](../../../docs/aws-deployment-guide.md).

This layer plugs into the core: it imports the core's exports, and no core stack is redeployed. Airflow runs every DAG task as an ECS task (`METAMORPH_TASK_LAUNCHER=ecs`, `dags/metamorph_pipeline/containers.py`). The connectors keep their stores, PDFs and MinerU caches on EFS. MinerU runs on one GPU instance, only in the ingest window.

| Stack | Template | What it adds |
|---|---|---|
| `metamorph-ingestion-shared` | [`shared.yaml`](shared.yaml) | Security groups for Airflow, the tasks, MinerU and EFS, with rules into the core's database group. Also EFS with one access point per connector, Cloud Map's `mineru.metamorph.internal`, the ingestion image repositories, the `metamorph-platform` role and the wiring parameters |
| `metamorph-ingestion-jobs` | [`jobs.yaml`](jobs.yaml) | The task definitions Airflow runs: `metamorph-platform` and the four connectors, plus `metamorph-ops` |
| `metamorph-ingestion-airflow` | [`airflow.yaml`](airflow.yaml) | Airflow as an ECS service, with the role that lets it run those tasks |
| `metamorph-ingestion-mineru` | [`mineru.yaml`](mineru.yaml) | A GPU Auto Scaling group with a warm pool, its capacity provider, the MinerU service, and the schedules that open and close its window |

## What the account must allow first

| Needed | For | Today |
|---|---|---|
| `iam:CreateRole` and its relatives, on `metamorph-*`, or an administrator creating the roles in the templates | Airflow's role (runs the tasks), the platform's and ops roles, the GPU instance's role, the window's scheduler role | denied |
| `elasticfilesystem:*` | the connectors' state | denied |
| `servicediscovery:*` | MinerU's private address | denied |
| `autoscaling:*`, and `ec2:RunInstances` for `g5.xlarge` | MinerU's GPU | denied (instances up to `*.large`) |
| `ssm:StartSession` | `tunnel.sh`: Airflow's UI from the Mac | denied |
| Running On-Demand G and VT instances quota (`L-DB2E81BA`), 8 vCPUs | the GPU | request it days ahead |

If the GPU stays out of reach, the jobs and Airflow stacks still work alone with `/metamorph/connectors/pdf-engine` set to `pymupdf`. The connectors then read PDFs as they did before MinerU, with byte-identical texts, and the readings already in the caches are kept for later.

## Plugging it in

The order, from the platform's directory with the core guide's Phase 0 shell lines. Every step names what it touches:

1. **The shared stack:** `deploy ingestion/shared --capabilities CAPABILITY_NAMED_IAM`. The core guide's `deploy` helper takes the path under `deploy/aws/` and names the stack `metamorph-ingestion-shared`. The roles it creates carry their own S3 permissions, so the core's bucket policies stay as they are.
2. **The settings:**
   - SecureString: `/metamorph/mineru/api-key`, `/metamorph/airflow/admin-password`, `/metamorph/airflow/webserver-secret`, `/metamorph/airflow/database-url` (`postgresql+psycopg2://metamorph:…@<host>:5432/airflow`), `/metamorph/bi/database-url` (`postgresql+psycopg://bi:<bi-password>@<host>:5432/bi`).
   - String: `/metamorph/connectors/pdf-engine` (`mineru`), `pdf-lines` (`printed`), `mineru-cache` (`data/mineru-cache`).
3. **Airflow's database:** a `metamorph-dbops` task with the command `psql -c 'CREATE DATABASE airflow'`.
4. **The images:** `TAG=$(date -u +%Y%m%d-%H%M)` on its own line, then `TAG=$TAG deploy/aws/push-images.sh airflow ojk-connector bpk-connector bi-connector dsn-mui-connector`, then `push-images.sh platform` if its tag moved.
5. **The task definitions:** `deploy ingestion/jobs --capabilities CAPABILITY_NAMED_IAM --parameter-overrides PlatformTag=… OjkTag=… BpkTag=… BiTag=… DsnTag=…`.
6. **The connectors' data into EFS:** tar the Mac's `{BI,BPK,OJK,DSN-MUI}-Source-Connector/data` without `exports/`, upload it to `s3://metamorph-ops-<account>/transfer/connector-data.tgz`, and unpack it with a `metamorph-ops` task (`… | tar -xzf - --no-same-owner --no-same-permissions -C /workspace`). **The MinerU caches are the one thing that costs money to rebuild.**
7. **MinerU** (only with the GPU): `deploy ingestion/mineru --capabilities CAPABILITY_NAMED_IAM`. Then build its image on the GPU instance:
   - hold the group in service with `--min-size 1`;
   - check `nvidia-smi` shows a driver of 580 or newer;
   - `docker build` and `docker push` `metamorph/mineru:4.0.12`;
   - set `--min-size 0` again.

   Open the window by hand and read the two step 9 PDFs with `mineru_check.py` from a BPK task.
8. **Airflow:** `deploy ingestion/airflow --capabilities CAPABILITY_NAMED_IAM --parameter-overrides AirflowTag=…`. Then unpause the DAGs.
9. **Retire the core guide's hand-run build.** `registry_build` now runs after every load.

The DAGs' schedules already fit MinerU's window, 00:30–03:15 UTC, and 04:30 on the 1st of the month (`jobs.py`, `mineru.yaml`'s parameters). Change both together.

## What it adds to the bill

These are Jakarta prices from 2026-10-23. Airflow keeps a database connection open, so Aurora stops pausing: count its 0.5 ACU floor.

| Item | Monthly |
|---|---:|
| Airflow: 0.5 vCPU, 3 GB, Fargate ARM, and its public IPv4 | about $28 |
| Connector and platform tasks: about 70 minutes a day | about $3 |
| EFS: about 6 GB, mostly Infrequent Access, with backups | about $2 |
| Aurora at its 0.5 ACU floor instead of pausing | about +$52 |
| The GPU instance's disk in the warm pool, and the MinerU image in ECR | about $12 |
| The GPU, g5.xlarge at $1.408 an hour, about 92 hours a month | about $130 |
| **Added** | **about $227**, or about $97 without MinerU |
