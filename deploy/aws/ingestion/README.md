# The ingestion layer: Airflow, the connectors and MinerU on ECS

Every night the nine source connectors run on AWS without the Mac. Airflow runs as an ECS service and starts each connector, load, build and publish step as an ECS task. The connectors keep their stores, PDFs and MinerU caches on EFS. MinerU runs on one `g5.xlarge` that EventBridge Scheduler starts before the ingest window and stops after it.

This layer plugs into the core: it imports only what the live core exports, and no core stack is redeployed for it (one exception, in step 1). **Deploy the core first:** [docs/aws-deployment-guide.md](../../../docs/aws-deployment-guide.md).

**No stack here creates an IAM resource or a Cloud Map namespace; the account allows neither.** Every role comes from DevOps, by name, as a stack parameter. The five roles, the instance profile and the permissions they carry are in [docs/aws-ingestion-permissions.md](../../../docs/aws-ingestion-permissions.md), and their policies are in [`deploy/aws/iam/`](../iam/). The organization also denies any create without the tag `Owner=project3`: the templates carry it, and the `deploy` helper below passes it as a stack tag. An untagged create fails as "explicit deny in a service control policy", which looks like a missing permission and is not one.

| Stack | Template | What it adds |
|---|---|---|
| `metamorph-ingestion-shared` | [`shared.yaml`](shared.yaml) | Security groups for Airflow, the tasks, MinerU's load balancer, the GPU host and EFS, with rules into the core's database group. One encrypted EFS file system with a mount target in each subnet and ten access points (one per connector, and the bundles). The ingestion image repositories (the nine connectors, Airflow and MinerU). The wiring parameters in Parameter Store |
| `metamorph-ingestion-jobs` | [`jobs.yaml`](jobs.yaml) | One task definition for every image a DAG runs: the nine connectors, the platform, and `metamorph-ops` (the platform image with a shell, which unpacks the moved data and runs the weekly backup). Tags: `PlatformTag`, `OjkTag`, `BpkTag`, `BiTag`, `DsnTag`, `OjkRegisterTag`, `OjkStatsTag`, `BiStatsTag`, `BpsStatsTag`, `ReportsTag`. Each connector mounts its own access point and the bundles, and no other connector's. There is no ops repository: ops runs the platform image |
| `metamorph-ingestion-mineru` | [`mineru.yaml`](mineru.yaml) | One `g5.xlarge` in cluster `metamorph`, the MinerU service on it behind an internal load balancer, the connectors' `/metamorph/connectors/mineru-url` setting, and three schedules that start and stop the instance. No Auto Scaling, no launch template |
| `metamorph-ingestion-airflow` | [`airflow.yaml`](airflow.yaml) | Airflow 2.10 as a Fargate service (LocalExecutor, metadata in the `airflow` database on `metamorph-pg`), behind an internal load balancer. The UI is reached through CloudFront, with a password checked at the edge by a CloudFront Function |
| `metamorph-ingestion-alerts` | [`alerts.yaml`](alerts.yaml) | An SNS topic with the owner's email, an EventBridge rule for Metamorph tasks that end with a failing container (a task that ECS stops itself in a service deploy is not one), and a CloudWatch alarm for Airflow with no running task for 10 minutes |

Two scripts sit beside the templates:
- [`waf.sh`](waf.sh) makes the rate-limit web ACL in front of Airflow's CloudFront address. It lives in us-east-1, where the organization denies CloudFormation, so the WAF CLI makes it.
- [`check.sh`](check.sh) reads the account and reports pass or fail for the roles, the stacks, EFS, MinerU and Airflow. It only reads, so run it whenever you want to know where things stand.

## Before you start

- The core is deployed, and the shell lines of the core guide's [Phase 0](../../../docs/aws-deployment-guide.md#phase-0-before-you-start) are set (`deploy`, `setting`, `secret`, `exported`). `deploy ingestion/shared` names its stack `metamorph-ingestion-shared`. None of these stacks needs `--capabilities`, because none creates IAM.
- DevOps has made the roles and the instance profile and raised the GPU quota. `deploy/aws/ingestion/check.sh` shows the roles first, so run it now: its first six lines must pass.
- The quota **Running On-Demand G and VT instances** (`L-DB2E81BA`) is at least 8 vCPUs. One `g5.xlarge` needs 4.
- The one-off task helper `run_task` from the core guide's Phase 4, step 2.

## The deployment order

1. **The shared stack.** `deploy ingestion/shared`. The core's foundation also needs one redeploy, once, for the lifecycle rule that expires the ops bucket's `backups/` after 35 days: `deploy foundation` with the parameters it was first deployed with (the guide's Phase 1). Until then, weekly backups pile up. The alerts stack (`deploy ingestion/alerts --parameter-overrides AlertEmail=…`, then confirm the subscription from the email SNS sends) needs only the core, so it can go now or at any time later.
2. **The settings and Airflow's database.**
   - SecureString (`secret NAME VALUE`): `/metamorph/mineru/api-key`, `/metamorph/airflow/admin-password`, `/metamorph/airflow/webserver-secret`, `/metamorph/airflow/database-url` (`postgresql+psycopg2://metamorph:…@<database host>:5432/airflow`), `/metamorph/bi/database-url` (`postgresql+psycopg://bi:<bi-password>@<database host>:5432/bi`). Optional: `/metamorph/airflow/alert-webhook-url`, Slack's webhook, with `AlertWebhook=yes` on the Airflow stack.
   - String: `/metamorph/connectors/pdf-engine` (`mineru`), `/metamorph/connectors/pdf-lines` (`printed`), `/metamorph/connectors/mineru-cache` (`data/mineru-cache`).
   - String, the contact each of four connectors adds to its User-Agent: `/metamorph/connectors/ojk-register-contact`, `/metamorph/connectors/ojk-stats-contact`, `/metamorph/connectors/bps-stats-contact`, `/metamorph/connectors/reports-contact`. Each is an email address or URL the sites can reach the operator at. They must exist (SSM takes no empty value, so use a real contact): ECS cannot start a task whose secret has no parameter, so the OjkRegister, OjkStats, BpsStats and Reports tasks would fail at start without them.
   - The database: `run_task dbops metamorph-sg-database-ops psql -c 'CREATE DATABASE airflow'`, run in the way the guide runs its other `metamorph-dbops` commands.
3. **The images.** From the platform's directory, with the tag on its own line:
   ```bash
   TAG=$(date -u +%Y%m%d-%H%M)
   TAG=$TAG deploy/aws/push-images.sh airflow ojk-connector bpk-connector bi-connector dsn-mui-connector \
     ojk-register ojk-stats bi-stats bps-stats reports
   TAG=$TAG deploy/aws/push-images.sh platform     # only if the platform's tag moved
   ```
   These are arm64 (Fargate's Graviton), built on the Mac from the working trees: commit first. Tags are immutable, so a rebuilt image needs a new tag.
4. **The task definitions.**
   ```bash
   deploy ingestion/jobs --parameter-overrides PlatformTag=… OjkTag=… BpkTag=… BiTag=… DsnTag=… \
     OjkRegisterTag=… OjkStatsTag=… BiStatsTag=… BpsStatsTag=… ReportsTag=…
   ```
5. **The connectors' data into EFS.** From the Mac, tar each connector's `data/` without its `exports/`, put it in the ops bucket (its `transfer/` copies expire after 14 days), and unpack it with a `metamorph-ops` task, which has every connector's `data/` and the bundles mounted. **The MinerU caches are the one thing that costs money to rebuild.** Keep the Mac's DAGs paused from here.
   ```bash
   tar -czf - -C ~/Work/Metamorph-Sharia --exclude=exports \
     OJK-Source-Connector/data BPK-Source-Connector/data BI-Source-Connector/data DSN-MUI-Source-Connector/data \
     OJK-Register-Connector/data OJK-Stats-Connector/data BI-Stats-Connector/data BPS-Stats-Connector/data \
     Reports-Connector/data | aws s3 cp - "s3://metamorph-ops-$ACCOUNT/transfer/connector-data.tgz"
   run_task ops metamorph-sg-jobs 'python -c "import boto3,os; boto3.client(\"s3\").download_file(os.environ[\"OPS_BUCKET\"], \"transfer/connector-data.tgz\", \"/tmp/d.tgz\")" \
     && tar -xzf /tmp/d.tgz --no-same-owner --no-same-permissions -C /workspace && rm /tmp/d.tgz && du -sh /workspace/*/data'
   ```
6. **MinerU, then its image checked against the step 9 PDFs.**
   - **The image must be in ECR before the stack deploys:** the service starts a task the moment the instance registers, and the instance role only pulls. MinerU's image is x86-64 and about 7 GB compressed. It is built natively by the CodeBuild project `metamorph-mineru-image` (medium, privileged, role `Project3CodeBuildRole`, which may push to ECR): zip `docker/mineru/Dockerfile` to `s3://metamorph-ops-$ACCOUNT/transfer/mineru-src.zip`, then `aws codebuild start-build --project-name metamorph-mineru-image` (about 11 minutes). Its buildspec tags the image with the stack's `MinerUTag` (default `4.0.12-r2`). Tags are immutable: a rebuild takes a new tag, in the buildspec and in `MinerUTag` together. Building on the Mac also works (`docker buildx build --platform linux/amd64 … --push docker/mineru`), but it emulates x86-64 and is far slower.
   - `deploy ingestion/mineru`. It writes `/metamorph/connectors/mineru-url` itself (the internal load balancer's address, port 8010).
   - **`InstanceSubnetIndex` defaults to 1, not 0.** `g5.xlarge` is offered only in ap-southeast-3a and 3c, and the core's `metamorph-subnets` lists its subnets in the order 3b, 3c, 3a: index 1 is 3c and index 2 is 3a. Redeploy with `InstanceSubnetIndex=2` if 3c has no G5 capacity.
   - The instance starts at 00:20 UTC and stops at 04:00 (04:30 on the 1st), by schedule (`WindowStart`, `WindowEnd`, `MonthlyWindowEnd`). To test outside the window, start it by hand with `aws ec2 start-instances` (its Name tag is `metamorph-mineru`), and stop it after.
   - The first start pulls the 20 GB image, and the service's 15 minute grace period covers that and the model load. Later starts reuse the image on the root disk.
   - Check `nvidia-smi` shows a driver of 580 or newer (a task can start only if it does).
   - Read the two step 9 PDFs with `packages/metamorph-pdf-text/scripts/mineru_check.py` from a BPK task. If MinerU can't be reached, the jobs and Airflow stacks still work alone with `/metamorph/connectors/pdf-engine` set to `pymupdf`: the connectors then read PDFs as they did before MinerU, and the readings already in the caches are kept for later.
7. **Airflow, with every DAG paused.** `deploy ingestion/airflow --parameter-overrides AirflowTag=… PasswordSha256=$(printf %s "$PASSWORD" | shasum -a 256 | cut -d' ' -f1)`. Airflow pauses a new DAG when it first reads it (its default), so all of them start paused. Choose the edge password and keep it somewhere safe: the stack takes only its SHA-256, never the password. Make it a different value from `/metamorph/airflow/admin-password`, which is Airflow's own `admin` sign-in, so that a leaked edge password alone grants nothing.
8. **The WAF script, then the UI address.** `deploy/aws/ingestion/waf.sh create` prints the web ACL's ARN. Redeploy Airflow with `WebAclArn=<that ARN>`. The stack's `Url` output is Airflow's address: the browser asks for the edge password (any user name), then Airflow's own sign-in (`admin`). There is no tunnel: the UI is reached through CloudFront.
9. **Each DAG once by hand, inside the window,** regulation connectors first (`ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa`), then the register, statistics and reports connectors. Start the instance by hand if you test outside the window. Each run is a connector's collect, its load and its build. **If a source refuses AWS's addresses (a 403, a 429 or a challenge page), stop that connector and leave its DAG paused. Never vary headers or addresses to get around a refusal.**
10. **Unpause every DAG except `ingest_bps_stats`,** which stays paused for its known issue.

## The gate

Go-live waits on three things:
- every DAG passes one hand run inside the window (step 9);
- `deploy/aws/ingestion/check.sh` passes, outside the window (it expects MinerU's instance stopped then);
- the first night of scheduled runs ends with no unexplained failure and `health` passing.

After that the alerts and the daily `health` DAG monitor without blocking: a task that fails in a connector emails the owner (the alerts stack), Airflow posts to Slack when its webhook is set, and a dead Airflow emails after 10 minutes.

## The window

MinerU's window starts at 00:20 UTC (ten minutes to boot and place the service, then the models load before `ingest_ojk` at 01:00) and ends at 04:00, or at 04:30 on the 1st for DSN-MUI's monthly full pass. Every job with `reads_pdfs` in `dags/metamorph_pipeline/jobs.py` must start inside it and at least an hour before its end (the Monday jobs run from 02:00 to 02:45), and `tests/test_ingestion_stacks.py` checks that: change the DAG schedules and the stack's window parameters together. The weekly backup (`backup_connector_data`, Sundays 05:00 UTC) starts after the last stop.

## Rollback

- Pause every DAG.
- For a MinerU-only fault, set `/metamorph/connectors/pdf-engine` to `pymupdf`.
- The Mac can resume: its data is untouched until the AWS run is trusted.
- The stacks can be deleted. EFS is kept by its retention setting; delete it by hand when you are sure.

## What it adds to the bill

Jakarta prices, rounded. The database is the existing `metamorph-pg`, so there is no new one.

| Item | Monthly |
|---|---:|
| Airflow: 0.5 vCPU, 3 GB, Fargate, and its public IPv4 | about $28 |
| Connector and platform tasks | about $3 |
| EFS, mostly Infrequent Access | about $2 |
| The GPU, `g5.xlarge` for about 2 to 3.7 hours a day (the window is 00:20 to 04:00) | about $85 to $160 |
| CloudFront and WAF in front of the UI | about $8 |
| The GPU instance's disk while stopped, the internal load balancer and the MinerU image in ECR | about $30 |
