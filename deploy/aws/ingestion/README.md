# The ingestion layer: collection on a host at home, processing on AWS

Most sources refuse AWS addresses (OJK drops the connection, BPK answers 403, BI closes it), so the connectors cannot collect from AWS. They run on a **collection host** on a residential line, at first the owner's Mac. Everything after a bundle exists (load, registry build, indexing, health) runs on AWS, next to the database. The two sides each have their own Airflow, and bundles in S3 are all that joins them. The reason is recorded in [ADR 0001](../../../docs/adr/0001-collection-on-a-residential-host.md); do not move collection back to AWS without reading it.

This layer plugs into the core: it imports only what the live core exports, and no core stack is redeployed for it (one exception, in step 1). **Deploy the core first:** [docs/aws-deployment-guide.md](../../../docs/aws-deployment-guide.md).

**No stack here creates an IAM resource or a Cloud Map namespace; the account allows neither.** Every role comes from DevOps, by name, as a stack parameter. The roles, the instance profile and the permissions they carry are in [docs/aws-ingestion-permissions.md](../../../docs/aws-ingestion-permissions.md), and their policies are in [`deploy/aws/iam/`](../iam/). The organization also denies any create without the tag `Owner=project3`: the templates carry it, and the `deploy` helper below passes it as a stack tag. An untagged create fails as "explicit deny in a service control policy", which looks like a missing permission and is not one.

## The two sides

The collection host and AWS each run their own Airflow, from the one `dags/` folder and the one job registry.

| | Collection host (the Mac) | AWS |
|---|---|---|
| Airflow | The local Compose stack, `METAMORPH_SIDE=collection`, Docker launcher | One ECS service, `METAMORPH_SIDE=processing`, ECS launcher |
| DAGs | Every `ingest_*` DAG (`ingest_ojk`, `ingest_bpk`, … `ingest_reports`) and `backup_connector_data` | `load_bundles`, `registry_build`, `market_publish`, `regulation_index`, `market_index` and `health` |
| What runs | Each connector in its own image: collect, export a bundle, then `metamorph upload-bundle`. Weekdays in working hours WIB, while the laptop is awake | The platform and retrieval tasks on Fargate |
| State | Connector stores, PDFs and MinerU caches on the Mac's disk. A weekly backup of every `data/` goes to the ops bucket | The database, the blobs bucket, the published corpus |
| Reaches | The sources, MinerU through its CloudFront front door, S3 as the owner's SSO session | The database, S3, the sources never |

An Airflow started without `METAMORPH_SIDE` fails with a message, so a misconfigured side never runs both halves. Each DAG module declares its side ([`dags/metamorph_pipeline/sides.py`](../../../dags/metamorph_pipeline/sides.py)).

**The bundle's trip.** The last tasks of an ingest DAG are `upload` and `discard`. `upload` copies the run's bundle to `s3://<blobs bucket>/bundles/<connector>/<run>/` and writes `_COMPLETE` last, so a bundle half-uploaded when the laptop slept is never loaded. `load_bundles` runs every 30 minutes and, for each connector, runs `metamorph load-pending s3://<blobs bucket>/bundles/<connector>` in the platform image: the complete bundles not yet loaded, oldest first, stopping at the first that fails. A load that succeeds updates its layer's registry, and `registry_build` or `market_publish` follows as before. The blobs bucket expires bundles after 35 days.

**The Mac needs** these in `.env` ([`.env.example`](../../../.env.example) explains each): `METAMORPH_AWS_PROFILE` (the SSO profile), `METAMORPH_BUNDLES_BUCKET` (`metamorph-blobs-<account>`), `METAMORPH_OPS_BUCKET` (`metamorph-ops-<account>`, for the backup), `METAMORPH_MINERU_URL` (the mineru stack's `FrontDoorUrl`) and `METAMORPH_MINERU_API_KEY`.

**Signing in again.** The jobs use the owner's SSO session, so no AWS key sits on the laptop. When it expires, only `upload` (and the backup) fail, with a message saying to sign in again: run `aws sso login --profile <the profile>`, then clear the failed `upload` task in the Airflow UI. The collected bundle is still on the Mac's disk, so nothing is collected twice. A day the laptop was closed is skipped, not queued (`catchup` is off): incremental connectors catch up on the next run.

**A held bundle.** See [A held bundle](#a-held-bundle).

## The stacks

| Stack | Template | What it adds |
|---|---|---|
| `metamorph-ingestion-shared` | [`shared.yaml`](shared.yaml) | Security groups for Airflow, the platform tasks, MinerU's load balancer and the GPU host, with rules into the core's database group. The Airflow and MinerU image repositories. The wiring parameters in Parameter Store |
| `metamorph-ingestion-jobs` | [`jobs.yaml`](jobs.yaml) | The platform's task definition (`metamorph-platform`): load, build, publish and health. Tag: `PlatformTag`. It reads bundles from the blobs bucket, so it mounts nothing. Retrieval's refresh is the retrieval stack's |
| `metamorph-ingestion-mineru` | [`mineru.yaml`](mineru.yaml) | One `g5.xlarge` in cluster `metamorph`, the MinerU service on it behind an internal load balancer, a CloudFront front door in front of that (the collection host's way in), and the schedules that start and stop the instance. No Auto Scaling, no launch template |
| `metamorph-ingestion-airflow` | [`airflow.yaml`](airflow.yaml) | Airflow 2.10 as a Fargate service (LocalExecutor, metadata in the `airflow` database on `metamorph-pg`), behind an internal load balancer. The UI is reached through CloudFront, with a password checked at the edge by a CloudFront Function |
| `metamorph-ingestion-alerts` | [`alerts.yaml`](alerts.yaml) | An SNS topic with the owner's email, an EventBridge rule for processing tasks (`metamorph-airflow`, `metamorph-platform`, `metamorph-retrieval`) that end with a failing container (a task that ECS stops itself in a service deploy is not one; MinerU's is excluded), and a CloudWatch alarm for Airflow with no running task for 10 minutes |

Two scripts sit beside the templates:
- [`waf.sh`](waf.sh) makes the rate-limit web ACL in front of a CloudFront address: `waf.sh create` (Airflow's UI) or `waf.sh create mineru` (MinerU's front door); `delete` takes the same target. It lives in us-east-1, where the organization denies CloudFormation, so the WAF CLI makes it.
- [`check.sh`](check.sh) reads the account and reports pass or fail for the roles, the stacks, MinerU's front door and instance, and Airflow. It only reads, so run it whenever you want to know where things stand.

## Before you start

- The core is deployed, and the shell lines of the core guide's [Phase 0](../../../docs/aws-deployment-guide.md#phase-0-before-you-start) are set (`deploy`, `setting`, `secret`, `exported`). `deploy ingestion/shared` names its stack `metamorph-ingestion-shared`. None of these stacks needs `--capabilities`, because none creates IAM.
- DevOps has made the roles and the instance profile and raised the GPU quota. `deploy/aws/ingestion/check.sh` shows the roles first, so run it now: its first five lines must pass.
- The quota **Running On-Demand G and VT instances** (`L-DB2E81BA`) is at least 8 vCPUs. One `g5.xlarge` needs 4.

## The deployment order, on AWS

1. **The shared stack.** `deploy ingestion/shared`. The core's foundation also needs one redeploy, once, for the lifecycle rules that expire the ops bucket's `backups/` and the blobs bucket's `bundles/` after 35 days: `deploy foundation` with the parameters it was first deployed with (the guide's Phase 1). Until then, backups and bundles pile up. The alerts stack (`deploy ingestion/alerts --parameter-overrides AlertEmail=…`, then confirm the subscription from the email SNS sends) needs only the core, so it can go now or at any time later.
2. **The settings and Airflow's database.**
   - SecureString (`secret NAME VALUE`): `/metamorph/mineru/api-key`, `/metamorph/airflow/admin-password`, `/metamorph/airflow/webserver-secret`, `/metamorph/airflow/database-url` (`postgresql+psycopg2://metamorph:…@<database host>:5432/airflow`). Optional: `/metamorph/airflow/alert-webhook-url`, Slack's webhook, with `AlertWebhook=yes` on the Airflow stack.
   - The database: `run_task dbops metamorph-sg-database-ops psql -c 'CREATE DATABASE airflow'`, run in the way the guide runs its other `metamorph-dbops` commands.
3. **The images.** From the platform's directory, with the tag on its own line:
   ```bash
   TAG=$(date -u +%Y%m%d-%H%M)
   TAG=$TAG deploy/aws/push-images.sh airflow platform
   ```
   These are arm64 (Fargate's Graviton), built on the Mac from the working trees: commit first. Tags are immutable, so a rebuilt image needs a new tag. The connectors' images are never pushed: they are built on the collection host (`docker compose --profile connectors build`).
4. **The platform's task definition.** `deploy ingestion/jobs --parameter-overrides PlatformTag=$TAG`.
5. **MinerU.**
   - **The image must be in ECR before the stack deploys:** the service starts a task the moment the instance registers, and the instance role only pulls. MinerU's image is x86-64 and about 7 GB compressed. It is built natively by the CodeBuild project `metamorph-mineru-image` (medium, privileged, role `Project3CodeBuildRole`, which may push to ECR): zip `docker/mineru/Dockerfile` to `s3://metamorph-ops-$ACCOUNT/transfer/mineru-src.zip`, then `aws codebuild start-build --project-name metamorph-mineru-image` (about 11 minutes). Its buildspec tags the image with the stack's `MinerUTag` (default `4.0.12-r2`). Tags are immutable: a rebuild takes a new tag, in the buildspec and in `MinerUTag` together. Building on the Mac also works (`docker buildx build --platform linux/amd64 … --push docker/mineru`), but it emulates x86-64 and is far slower.
   - `deploy ingestion/mineru`.
   - **The front door:** the stack's `FrontDoorUrl` output is MinerU's address off AWS, checked by MinerU's own API key (no edge password). Make its rate limit first, as for Airflow's: `deploy/aws/ingestion/waf.sh create mineru` prints the web ACL's ARN, and `deploy ingestion/mineru --parameter-overrides WebAclArn=<that ARN>` attaches it. Its load balancer is in the private subnets, which cover zones 3b and 3c only, so keep `InstanceSubnetIndex` at 1.
   - **`InstanceSubnetIndex` defaults to 1, not 0.** `g5.xlarge` is offered only in ap-southeast-3a and 3c, and the core's `metamorph-subnets` lists its subnets in the order 3b, 3c, 3a: index 1 is 3c and index 2 is 3a. Redeploy with `InstanceSubnetIndex=2` if 3c has no G5 capacity.
   - The first start pulls the 20 GB image, and the service's 15 minute grace period covers that and the model load. Later starts reuse the image on the root disk. Check `nvidia-smi` shows a driver of 580 or newer (a task can start only if it does).
   - Read two PDFs through the front door from the Mac with `packages/metamorph-pdf-text/scripts/mineru_check.py` (`METAMORPH_MINERU_URL` and `METAMORPH_MINERU_API_KEY` set), inside the window. If MinerU can't be reached, a connector job can still run with `METAMORPH_PDF_ENGINE=pymupdf`: it reads PDFs as it did before MinerU, and the readings already in the caches are kept for later.
6. **Airflow, with every DAG paused.** `deploy ingestion/airflow --parameter-overrides AirflowTag=$TAG PasswordSha256=$(printf %s "$PASSWORD" | shasum -a 256 | cut -d' ' -f1)`. Airflow pauses a new DAG when it first reads it (its default), so all of them start paused. Choose the edge password and keep it somewhere safe: the stack takes only its SHA-256, never the password. Make it a different value from `/metamorph/airflow/admin-password`, which is Airflow's own `admin` sign-in, so that a leaked edge password alone grants nothing.
7. **The WAF script, then the UI address.** `deploy/aws/ingestion/waf.sh create` prints the web ACL's ARN. Redeploy Airflow with `WebAclArn=<that ARN>`. The stack's `Url` output is Airflow's address: the browser asks for the edge password (any user name), then Airflow's own sign-in (`admin`). There is no tunnel: the UI is reached through CloudFront.
8. **Unpause the processing DAGs:** `load_bundles`, `registry_build`, `market_publish`, `regulation_index`, `market_index` and `health`.

## The collection host

Set up once, on the Mac, from the platform's directory:

```bash
cp .env.example .env     # METAMORPH_WORKSPACE, and the five settings listed under "The two sides"
aws sso login --profile <the profile>
docker compose --profile connectors build      # the platform image and the connector images
docker compose up -d                           # Airflow at :8080, collection side
```

The DAGs ship paused. Unpause an `ingest_*` DAG to enable its source, pause it to disable it; trigger one by hand to rerun or debug a single source. Each job's schedule is one line in the job registry ([`dags/metamorph_pipeline/jobs.py`](../../../dags/metamorph_pipeline/jobs.py)), and adding a source is one more job there. `ingest_bps_stats` stays paused for its known issue. Keep the Mac plugged in and awake while a run is going: a run cut off by sleep is simply retried.

## The cutover

Collection moves to the Mac, and nothing on AWS is deleted until the gate passes, so a failed cutover can still fall back. Before step 1, finish "The deployment order" above: the platform image has to be one that has `load-pending` and `load_bundles`. If the platform's task definition was last deployed before that image, register it with the template as it was before the retirement (`git show 11be20e:deploy/aws/ingestion/jobs.yaml`, deployed with the new `PlatformTag`): that template still has the connector task definitions, which are the fallback until step 5. The connectors' EFS copy of their state is not carried over: the Mac's own `data/` is the authoritative copy (DSN-MUI's three newer fatwas are already published and reload unchanged).

1. **A hand run of each ingest DAG, from the Mac, inside MinerU's window** (weekdays 08:45 to 12:45 WIB; the PDF jobs start between 09:00 and 11:30). Regulation connectors first (`ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa`), then the register, statistics and reports connectors. Start MinerU by hand if you test outside the window ([The window](#the-window)). A run ends with its bundle uploaded.
2. **Its bundle is loaded on AWS.** `load_bundles` picks it up within 30 minutes (or trigger it in AWS's Airflow). The connector's `load_*` task succeeds, then `registry_build` (or `market_publish`) and the indexes follow.
3. **Health passes.** `health` passes for every enabled connector, and `deploy/aws/ingestion/check.sh` passes, outside the window (it expects MinerU's instance stopped then).
4. **The first scheduled weekday runs on its own.** The DAGs are unpaused, the laptop is awake, and the day's bundles load and publish with no hand in it.
5. **Then deploy the retirement.** The next section.

If a source refuses the Mac too (a 403, a 429 or a challenge page), stop that connector and leave its DAG paused. Never vary headers or addresses to get around a refusal.

After the gate the alerts and the daily `health` DAG monitor without blocking: a processing task that fails emails the owner (the alerts stack), Airflow posts to Slack when its webhook is set, and a dead Airflow emails after 10 minutes. A dead or sleeping collection host raises no alert of its own: `health` flags the connector whose bundles stop arriving.

## The retirement

Only after the gate. It removes what ran collection on AWS: the nine connector task definitions and the ops task, their EFS and its access points, the connector image repositories, and the settings only they read. Deploy in this order, because a stack cannot drop an export another stack still imports:

1. **Empty the nine connector repositories**, since CloudFormation will not delete a repository that holds images:
   ```bash
   for r in ojk-connector bpk-connector bi-connector dsn-mui-connector ojk-register ojk-stats bi-stats bps-stats reports; do
     ids=$(aws ecr list-images --repository-name metamorph/$r --query 'imageIds[*]' --output json)
     aws ecr batch-delete-image --repository-name metamorph/$r --image-ids "$ids"
   done
   ```
2. **`deploy ingestion/jobs --parameter-overrides PlatformTag=…`.** The connector and ops task definitions go, and the platform's loses its EFS mount. (Their old revisions stay in ECS, inactive.)
3. **`deploy ingestion/shared`.** The file system, its access points, mount targets and security group, the connector repositories, and the jobs-to-MinerU load balancer rule go. The file system has `DeletionPolicy: Retain`: it stays until you delete it by hand (`aws efs delete-file-system`), when you are sure nothing is needed from it.
4. **`deploy ingestion/mineru`.** The internal address (`/metamorph/connectors/mineru-url` and the `MinerUUrl` output) goes: connectors reach MinerU through `FrontDoorUrl` now.
5. **`deploy ingestion/alerts --parameter-overrides AlertEmail=…`.** The rule then lists only the processing families.
6. **Delete the settings only connector tasks read:**
   ```bash
   aws ssm delete-parameters --names /metamorph/connectors/pdf-lines /metamorph/connectors/pdf-engine \
     /metamorph/connectors/mineru-cache /metamorph/connectors/ojk-register-contact /metamorph/connectors/ojk-stats-contact \
     /metamorph/connectors/bps-stats-contact /metamorph/connectors/reports-contact /metamorph/bi/database-url /metamorph/ops/bucket
   ```
   `/metamorph/mineru/api-key` stays: MinerU checks it. The `bi` database on `metamorph-pg` is left as it is.
7. **Tell DevOps** the `metamorph-connector-task` role and the EFS permissions are no longer used, if they want to remove them.

Airflow's own settings stay (`/metamorph/airflow/*`).

## A held bundle

A bundle that fails to load is **held**: `load-pending` stops at it, leaves that connector's later bundles for the next pass (so the registry never skips a step for that source), prints `{"loaded", "skipped", "incomplete", "held", …}` and exits 1. The connector's `load_*` task in `load_bundles` then fails, and the failure alerts (the SNS email, Slack if set). The other connectors' tasks go on.

Because the failed task emits no registry update, **no build runs for the bundles that same pass loaded before the hold**: the registry build (or market publish) waits until the held bundle loads. Find the cause in the task's log (`metamorph-platform/main` in `/metamorph`). The next pass tries it again after the task's retry; once it loads, the task succeeds, the registry updates, and one build covers everything loaded since. A bundle without `_COMPLETE` is ignored, not held: it is still uploading, or an upload failed on the Mac and waits for a retry there.

## The window

The collection host runs on weekdays in working hours, so MinerU's window does too. It starts at 01:45 UTC, 08:45 WIB on Monday to Friday (a quarter of an hour to boot and place the service, then the models load before `ingest_ojk` at 02:00), and ends at 05:45 UTC (12:45 WIB). On the month's first weekday, when DSN-MUI's full pass runs, it ends at 06:15 UTC (13:15 WIB). That weekday is always the 1st, 2nd or 3rd, so `MonthlyWindowEnd` covers those three days, and a second weekday among them runs half an hour longer than it needs. Every job with `reads_pdfs` in `dags/metamorph_pipeline/jobs.py` must start inside the window and at least an hour before its end (the jobs run from 02:00 to 03:45 UTC, 09:00 to 10:45 WIB), and `tests/test_ingestion_stacks.py` checks that: change the DAG schedules and the stack's window parameters together. The weekly backup (`backup_connector_data`, Fridays 07:00 UTC) starts after the last stop.

A stop repeats every hour on the hour outside the window (`HourlyStop`), so a hand start costs at most an hour of GPU. **To run a PDF job in the afternoon, start MinerU by hand** as your SSO role (it needs `ec2:DescribeInstances`, `StartInstances` and `StopInstances`, which `Project3Learner` has; the instance's Name tag is `metamorph-mineru`), and wait about 10 minutes for the models to load:

```bash
aws ec2 start-instances --instance-ids "$(aws ec2 describe-instances --filters Name=tag:Name,Values=metamorph-mineru \
  --query 'Reservations[].Instances[].InstanceId' --output text)"
```

Run it again each hour to keep it up, or stop it sooner with `aws ec2 stop-instances` and the same instance id.

## Rollback

- A source or a connector misbehaves: pause its DAG on the Mac.
- A bundle will not load: see [A held bundle](#a-held-bundle).
- MinerU only: set `METAMORPH_PDF_ENGINE=pymupdf` in the Mac's `.env`.
- Before the retirement, AWS can still run a connector from its task definition if a source ever accepts AWS again. After it, redeploy the previous `jobs.yaml` and `shared.yaml` from git: the EFS copy of the connectors' data is gone with the file system, so restore a connector's `data/` from the Mac's weekly backup (`s3://<ops bucket>/backups/<date>/<connector>.tgz`).

## What it adds to the bill

Jakarta prices, rounded. The database is the existing `metamorph-pg`, so there is no new one.

| Item | Monthly |
|---|---:|
| Airflow: 0.5 vCPU, 3 GB, Fargate, and its public IPv4 | about $28 |
| Platform tasks (load, build, publish, health) | under $3 |
| The GPU, `g5.xlarge` for the weekday window (4 hours, 5 on a month's first weekday) | about $115 |
| CloudFront and WAF in front of the UI and MinerU's front door | about $16 |
| The GPU instance's disk while stopped, the internal load balancer and the MinerU image in ECR | about $30 |
