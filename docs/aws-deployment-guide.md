# Deploying Metamorph on AWS (Jakarta): ECS, RDS and Parameter Store

**Date:** 2026-10-23 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Status:** designed and written. The templates pass `cfn-lint` and the DAGs load under both launchers, but nothing has been created on AWS yet · **Architecture:** [deployment-architecture.md](deployment-architecture.md) · **Files:** [`deploy/aws/`](../deploy/aws)

This guide moves the whole stack off the Mac and onto AWS:
- the four connectors and the platform's tasks;
- Airflow;
- PostgreSQL;
- the curation API and web app;
- MinerU.

**Every service is its own ECS service or task.** Each one starts, stops, scales and is redeployed without touching the others. The database is Amazon RDS. Every setting a container reads from its environment comes from Parameter Store, under `/metamorph/`. Within those choices, the guide aims for the lowest cost that still runs the pipeline unattended.

## Contents

1. [The design](#the-design)
2. [Settings in Parameter Store](#settings-in-parameter-store)
3. [What it costs](#what-it-costs)
4. [What changed in the code](#what-changed-in-the-code)
5. [Phase 0: before AWS](#phase-0-before-aws)
6. [Phase 1: the foundation](#phase-1-the-foundation)
7. [Phase 2: settings and the database](#phase-2-settings-and-the-database)
8. [Phase 3: the images](#phase-3-the-images)
9. [Phase 4: move the data from the Mac](#phase-4-move-the-data-from-the-mac)
10. [Phase 5: the services](#phase-5-the-services)
11. [Phase 6: MinerU and its window](#phase-6-mineru-and-its-window)
12. [Phase 7: check, then go live](#phase-7-check-then-go-live)
13. [Operating it](#operating-it)
14. [What can go wrong](#what-can-go-wrong)
15. [Appendix: the operator's permissions](#appendix-the-operators-permissions)

## The design

```
 Curators ── HTTPS ──► Application Load Balancer (ACM certificate) ──► web       Fargate, always on
                                                                         │ http://api.metamorph.internal:8001 (Cloud Map)
                                                                         ▼
                                                                       api       Fargate, always on ──► S3 blobs
 ┌ ECS cluster "metamorph" ──────────────────────────────────────────────────────────────────────────────────────────┐
 │ airflow   Fargate, always on: scheduler + UI (UI only through deploy/aws/tunnel.sh)                               │
 │   └─ RunTask, per DAG task ─► metamorph-ojk/bpk/bi/dsn-mui-connector, metamorph-platform   Fargate, minutes a day │
 │                                 │ EFS: each connector's data/ (stores, PDFs, mineru-cache) and /bundles           │
 │                                 └─ http://mineru.metamorph.internal:8010 + API key                                │
 │ mineru    ECS on EC2: one g5.xlarge from a warm pool, only in the ingest window (EventBridge Scheduler)           │
 └───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 RDS PostgreSQL 16 (db.t4g.small): metamorph, bi, airflow · Parameter Store /metamorph/* · CloudWatch Logs /metamorph
```

| Service | Runs as | Stack | Stop it / start it |
|---|---|---|---|
| Curation web app | ECS service `web`, Fargate ARM, 0.25 vCPU, 0.5 GB | `metamorph-web` | `aws ecs update-service --cluster metamorph --service web --desired-count 0` / `1` |
| Curation API | ECS service `api`, Fargate ARM, 0.25 vCPU, 1 GB | `metamorph-api` | the same, `--service api` |
| Airflow | ECS service `airflow`, Fargate ARM, 0.5 vCPU, 3 GB | `metamorph-airflow` | the same, `--service airflow`. Stopped, no DAG runs |
| MinerU | ECS service `mineru`, on a GPU capacity provider | `metamorph-mineru` | its window does it. By hand: `--service mineru --desired-count 1` |
| Connectors, platform tasks | ECS task definitions, run by Airflow | `metamorph-jobs` | pause the DAG in Airflow |
| PostgreSQL | RDS `metamorph` | `metamorph-database` | `aws rds stop-db-instance --db-instance-identifier metamorph`. RDS starts it again by itself after 7 days |

A desired count set with the CLI stays until the next update of that service's stack. To keep a service stopped across stack updates, deploy its stack with `DesiredCount=0`.

**The choices, and why:**

| Choice | Why | Rejected, with its monthly cost |
|---|---|---|
| **Fargate on Graviton (ARM64)** for everything without a GPU | No servers to patch, billed by the second, and ARM is 20% cheaper than x86 in Jakarta ($0.04045 against $0.05056 per vCPU-hour). The Mac is arm64, so every image but MinerU's already builds and runs on it | **ECS on EC2** for these services: a server to manage again, and it runs all month |
| **The connectors as task definitions that Airflow runs, not services** | They run for minutes a day. A task costs only while it runs: about $3 a month for all of them | Always-on connector services: about $35 a month each, mostly idle |
| **MinerU on ECS on EC2, with an Auto Scaling group that rests at zero** | Fargate has no GPU. ECS's capacity provider turns the service's desired count into an instance, so MinerU starts and stops like the others: its desired count is set to 1 or 0 | **An always-on g5.xlarge:** $1,028 |
| **A warm pool of one stopped instance** | A stopped instance keeps its disk. The 19.6 GB MinerU image stays on it, so a window starts in minutes instead of pulling the image every morning. You pay for the disk only | A fresh instance every window: a 20 GB pull each morning |
| **EventBridge Scheduler opens and closes the window** | Free. It calls `ecs:UpdateService` itself, so there's no Lambda to maintain | Airflow scaling MinerU from inside the DAGs: couples every DAG to MinerU's lifecycle |
| **RDS PostgreSQL 16, db.t4g.small, Single-AZ** | Managed backups (7 days of point-in-time recovery), patching and storage that grows by itself. 2 GiB holds the three databases | **Multi-AZ:** twice the price, for a pipeline that tolerates an hour of downtime. **Aurora Serverless v2:** its minimum capacity costs more than this instance |
| **EFS for the connectors' state** | Fargate tasks can't keep a disk between runs. Elastic throughput bills only what is read and written. Files not read for 30 days move to Infrequent Access at a fifteenth of the price | S3 for the stores: the connectors use SQLite and plain files, and changing that is a code change |
| **An Application Load Balancer** for the web app, with a free ACM certificate | Health checks, rolling deployments and HTTPS | **API Gateway HTTP API:** cheaper, but it buffers Next.js's streamed pages and cuts requests at 30 seconds |
| **Public subnets with a public IP per task, no NAT gateway** | Tasks need outbound access: the sources' websites, ECR, Parameter Store. Each public IPv4 address costs $3.65 a month. Inbound, every security group but the load balancer's is closed | **NAT gateway:** $43 a month plus $0.059 per GB. **VPC endpoints:** about $7 a month each, and five are needed |
| **Cloud Map DNS** (`api.metamorph.internal`, `mineru.metamorph.internal`) | Tasks change address on every start. Cloud Map costs $0.10 per registered task a month | **Service Connect:** an Envoy sidecar in every task |
| **Parameter Store, standard tier** | Free, and encrypted with the account's `aws/ssm` key. ECS reads it into each container at start | **Secrets Manager:** $0.40 per secret a month, and rotation isn't needed here |
| **Airflow `standalone` on one Fargate task** | Its scheduler and UI, as on the Mac. Its database is in RDS, so a new task carries on where the old one stopped | **Amazon MWAA:** a managed environment, costing many times this task |
| **CloudFormation, one stack per service** | Each stack creates, updates or deletes one service and nothing else. Every change is reviewable and reversible | Console clicks or bare CLI calls: nothing records what was made |

**What stays the same:**
- **The code:** every image, every connector and the schema. The one exception is the DAG launcher ([below](#what-changed-in-the-code)).
- **The MinerU cache key.** Every reading in the connectors' `mineru-cache` moves to EFS with them, so a PDF already read is never read again.
- **The MinerU image:** new files are read by the same pinned image (`docker/mineru/Dockerfile`), on the same GPU family as step 9.

**What has been checked (2026-10-23):**
- **The templates:** all seven pass `cfn-lint` for `ap-southeast-3`.
- **The DAGs load in Airflow 2.10.5 under both launchers.** Under `ecs`, every task becomes an `EcsRunTaskOperator` for the right task definition. `{{ ts_nodash }}` renders into its command. An unknown launcher fails loudly.
- **A test ties the DAGs to the template:** `tests/test_dag_jobs.py` checks that every image a DAG runs has its task definition in `jobs.yaml`.
- **The Airflow image** (`docker/airflow.Dockerfile`) builds with the DAGs inside and includes the Amazon provider. Its entrypoint creates the admin account from the password in Parameter Store, and a restart keeps that account.
- **`push-images.sh`** was run with stubs, and every build command is right. `tunnel.sh` passes `bash -n`.

**What hasn't been checked:** anything on AWS. The AWS commands follow AWS's documentation but haven't been run.

## Settings in Parameter Store

Every value a container reads from its environment is a parameter under `/metamorph/`, and the task definitions name them. Only the AWS region and a few fixed values, such as Airflow's executor, are written in the templates.

| Parameter | Type | Written by | Read by |
|---|---|---|---|
| `/metamorph/database/master-password` | SecureString | you, Phase 2 | RDS, when the database stack creates it |
| `/metamorph/database/bi-password` | SecureString | you, Phase 2 | you, when you create BI's role (Phase 4) |
| `/metamorph/database/host` | String | the database stack | you, to build the URLs below |
| `/metamorph/platform/database-url` | SecureString | you, Phase 2 | the platform's tasks, the API |
| `/metamorph/platform/s3-bucket` | String | the foundation stack | the platform's tasks, the API |
| `/metamorph/api/curators` | SecureString | you, Phase 2 | the API |
| `/metamorph/api/web-secret` | SecureString | you, Phase 2 | the API |
| `/metamorph/web/api-url` | String | the foundation stack | the web app |
| `/metamorph/bi/database-url` | SecureString | you, Phase 2 | the BI connector |
| `/metamorph/connectors/pdf-engine` | String: `mineru` | you, Phase 2 | the four connectors: **one setting rolls every connector back** (`pymupdf`) |
| `/metamorph/connectors/pdf-lines` | String: `printed` | you, Phase 2 | the four connectors |
| `/metamorph/connectors/mineru-cache` | String: `data/mineru-cache` | you, Phase 2 | the four connectors |
| `/metamorph/connectors/mineru-url` | String | the foundation stack | the four connectors |
| `/metamorph/mineru/api-key` | SecureString | you, Phase 2 | MinerU, and the four connectors |
| `/metamorph/airflow/database-url` | SecureString | you, Phase 2 | Airflow |
| `/metamorph/airflow/admin-password` | SecureString | you, Phase 2 | Airflow (the `admin` account) |
| `/metamorph/airflow/webserver-secret` | SecureString | you, Phase 2 | Airflow |
| `/metamorph/airflow/ecs-cluster`, `ecs-subnets`, `ecs-security-group`, `ecs-log-group` | String | the foundation stack | Airflow: where it runs the DAG tasks |
| `/metamorph/airflow/alert-webhook-url` | SecureString, optional | you | Airflow, when its stack has `AlertWebhook=yes` |
| `/metamorph/ops/bucket` | String | the foundation stack | the `metamorph-ops` task |

CloudFormation can't create SecureStrings, so you write the secret ones with the CLI. The stacks write the String ones for the resources they create.

**Changing a setting:** `aws ssm put-parameter --name … --value … --overwrite`.
- **A connector or platform task** reads its settings when it starts, so the next DAG run picks up the change.
- **A service** keeps the settings it started with. Restart it: `aws ecs update-service --cluster metamorph --service api --force-new-deployment`.

## What it costs

These are Jakarta on-demand prices from AWS's public price list files, read on 2026-10-23. Check them again in the console before you launch.

**Fixed, every month:**

| Item | Rate | Monthly |
|---|---|---:|
| Web app: 0.25 vCPU, 0.5 GB, Fargate ARM | $0.04045 per vCPU-hour, $0.00442 per GB-hour | $9.00 |
| API: 0.25 vCPU, 1 GB | | $10.61 |
| Airflow: 0.5 vCPU, 3 GB | | $24.44 |
| Connector and platform tasks: 1 vCPU, 4 GB, about 70 minutes a day in all | | about $3 |
| RDS db.t4g.small, Single-AZ | $0.051 an hour | $37.23 |
| RDS storage, 20 GB gp3. Backups up to 20 GB are free | $0.138 per GB-month | $2.76 |
| Application Load Balancer, with its few LCUs | $0.0252 an hour, $0.008 per LCU-hour | about $19 |
| Public IPv4: web, API and Airflow, and the load balancer's two | $0.005 an hour each | $18.25 |
| EFS: about 6 GB, most in Infrequent Access, plus its reads, writes and daily backups | $0.36 or $0.02 per GB-month, $0.04 per GB read, $0.07 per GB written | about $2 |
| The GPU instance's 100 GB disk, kept while it waits stopped in the warm pool | $0.096 per GB-month | $9.60 |
| ECR (about 15 GB, mostly MinerU), CloudWatch Logs (30 days), Cloud Map, S3 | | about $3.70 |
| Budgets, Parameter Store standard, EventBridge Scheduler, ACM | free | $0 |
| **Fixed total** | | **about $140** |

**The GPU,** g5.xlarge at **$1.408 an hour.** It runs from 00:30 to 03:15 UTC (07:30–10:15 WIB), plus about 15 minutes after each window while ECS scales the instance in. On the 1st of the month it runs until 04:30, for DSN-MUI's full pass. That comes to about 92 hours a month: **about $130.**

| | Monthly |
|---|---:|
| **Total, daily ingest** | **about $270** |
| Total with ingest twice a week (the DAG schedules as `… * * 1,4`, and the window's schedules to match) | about $177 |
| The single-EC2-host design this replaces, for comparison | about $190 |

ECS, RDS and Parameter Store cost about $80 a month more than one EC2 host running Compose:
- RDS: $40;
- the load balancer and the public addresses: $30;
- Fargate's always-on services instead of the host's spare capacity: about $10.

That buys services that stop, start and deploy independently, managed database backups, and no server to patch.

**Savings to take once it runs steadily:**

| Knob | How | Saves a month |
|---|---|---:|
| The web app and API only in working hours | Two Scheduler schedules like MinerU's, `desired-count` 0 at 12:00 UTC and 1 at 00:00 UTC on weekdays | about $15 |
| Airflow only around the window | The same, from 00:15 to 06:30 UTC. Move the `health` DAG's 06:00 run inside it. Curators don't need Airflow | about $22 |
| db.t4g.micro (1 GiB) | Redeploy the database stack with `InstanceClass=db.t4g.micro` once the nightly build is known to fit | $18.60 |
| A 1-year Compute Savings Plan (covers Fargate) and a 1-year RDS reservation | After a month of steady use | about $20 |

**Guardrails, all free:**
- **A budget** with email alerts at 50%, 80% and 100% (Phase 1).
- **The window closes by itself**, from three schedules that don't depend on Airflow.
- **The Auto Scaling group can't grow beyond one GPU instance** (`MaxSize: 1`).

## What changed in the code

ECS needs one code change, in the outermost ring: the place where Airflow builds its operators. Clean architecture had already isolated it there.

- **`dags/metamorph_pipeline/containers.py`** builds every operator, as before. `METAMORPH_TASK_LAUNCHER` chooses which kind:
  - `docker`, the default: the local Compose stack, unchanged;
  - `ecs`: an `EcsRunTaskOperator`.

  The ECS one passes only the command. The task definition holds the volumes and settings that the Docker operator passes as mounts and environment. No DAG changed.
- **`dags/metamorph_pipeline/jobs.py`**, the plain-data ring, gains `task_family(image)`: the task definition an image runs as (`metamorph/ojk-connector:dev` → `metamorph-ojk-connector`). It also now holds `PLATFORM_IMAGE`.
- **`tests/test_dag_jobs.py`** checks that every image a DAG runs has its task definition in `deploy/aws/jobs.yaml`, with the container `main`. A connector added to one place and not the other then fails a test, not a 1 a.m. run.
- **`docker/airflow.Dockerfile`** puts the DAGs inside the Airflow image, because Fargate has no bind mounts.
- **The ingest schedules now fit one GPU window.** The runs start 20 minutes apart, so they never compete for MinerU's one queue. The local stack follows the same times.

  | DAG | Before | Now (UTC) |
  |---|---|---|
  | `ingest_ojk` | `0 1 * * *` | `0 1 * * *` |
  | `ingest_bpk` | `0 2 * * *` | `20 1 * * *` |
  | `ingest_bi` | `0 3 * * *` | `40 1 * * *` |
  | `ingest_dsn_fatwa` | `0 4 * * 1` | `0 2 * * 1` |
  | `ingest_dsn_fatwa_full` | `0 16 1 * *` | `30 2 1 * *`, after the weekly run when the 1st is a Monday |

  The window's schedules (`mineru.yaml`'s parameters) assume these times. If you change one, change the other.

## Phase 0: before AWS

None of this costs anything.

1. **Check your access.** At step 9, the company account allowed SageMaker AI only. This deployment needs CloudFormation, ECS, EC2, Auto Scaling, ELB, RDS, EFS, ECR, S3, IAM roles, Parameter Store, Session Manager, Cloud Map, EventBridge Scheduler, ACM, CloudWatch Logs, AWS Backup and Budgets. The [appendix](#appendix-the-operators-permissions) has the policy to ask the account's administrator for.
2. **Request the GPU quota now:** it is the likeliest blocker. *Running On-Demand G and VT instances* (`L-DB2E81BA`) counts vCPUs: a g5.xlarge needs 4, and the g5.2xlarge fallback 8. Request 8:
   ```bash
   aws service-quotas request-service-quota-increase --region ap-southeast-3 \
       --service-code ec2 --quota-code L-DB2E81BA --desired-value 8
   ```
3. **Install the tools on the Mac:** the AWS CLI v2 and the Session Manager plugin. Docker Desktop is already there.
   ```bash
   brew install awscli && brew install --cask session-manager-plugin
   aws configure sso                 # or `aws configure` with an IAM user's key
   aws configure set region ap-southeast-3
   aws sts get-caller-identity
   ```
4. **Choose the curation app's host name,** for example `curation.<your-domain>`. You must be able to add CNAME records in its DNS.
5. **Commit and push** every repository. Images are built from the working trees, and MinerU's from the platform's committed `HEAD`. A tag should always name code that is in git.

Every later command runs from `~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform`, in a shell with:

```bash
export AWS_REGION=ap-southeast-3
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
setting() { aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text; }
secret() { aws ssm put-parameter --name "$1" --type SecureString --value "$2" --overwrite >/dev/null; }
deploy() { aws cloudformation deploy --stack-name "metamorph-$1" --template-file "deploy/aws/$1.yaml" \
             --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset "${@:2}"; }
```

## Phase 1: the foundation

1. **The default VPC and its three subnets,** one per Availability Zone:
   ```bash
   VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
   SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
               --query 'Subnets[].SubnetId' --output text | tr '\t' ',')
   echo "$VPC $SUBNETS"          # three subnet IDs
   ```
2. **The foundation stack.** It creates:
   - the cluster, the security groups and the log group;
   - Cloud Map's `metamorph.internal`;
   - EFS with its access points;
   - the `metamorph-blobs-<account>` and `metamorph-ops-<account>` buckets;
   - the eight ECR repositories;
   - the shared roles;
   - the wiring parameters.
   ```bash
   deploy foundation --parameter-overrides VpcId="$VPC" Subnets="$SUBNETS"
   ```
3. **The budget.** Budgets can't be made by CloudFormation in Jakarta, so use the CLI. Set it about 10% above your expected total:
   ```bash
   EMAIL=you@example.com LIMIT=300
   python3 -c "import json; print(json.dumps([{'Notification': {'NotificationType': 'ACTUAL', 'ComparisonOperator': 'GREATER_THAN', 'Threshold': t}, 'Subscribers': [{'SubscriptionType': 'EMAIL', 'Address': '$EMAIL'}]} for t in (50, 80, 100)]))" > /tmp/budget-alerts.json
   aws budgets create-budget --account-id "$ACCOUNT" \
     --budget "{\"BudgetName\":\"metamorph\",\"BudgetLimit\":{\"Amount\":\"$LIMIT\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
     --notifications-with-subscribers file:///tmp/budget-alerts.json
   ```

## Phase 2: settings and the database

1. **The secrets that come before the database,** each generated here and never shown:
   ```bash
   secret /metamorph/database/master-password "$(openssl rand -hex 24)"
   secret /metamorph/database/bi-password "$(openssl rand -hex 24)"
   secret /metamorph/mineru/api-key "$(openssl rand -hex 24)"
   secret /metamorph/airflow/admin-password "$(openssl rand -hex 16)"
   secret /metamorph/airflow/webserver-secret "$(openssl rand -hex 32)"
   secret /metamorph/api/web-secret "$(openssl rand -hex 32)"
   for pair in pdf-engine=mineru pdf-lines=printed mineru-cache=data/mineru-cache; do
     aws ssm put-parameter --name "/metamorph/connectors/${pair%%=*}" --type String --value "${pair#*=}" --overwrite >/dev/null
   done
   ```
2. **The curators' accounts,** copied from the Mac's `.env` without being printed:
   ```bash
   python3 - <<'EOF'
   import pathlib, shlex, subprocess
   line = next(l for l in pathlib.Path(".env").read_text().splitlines() if l.startswith("METAMORPH_CURATORS="))
   value = shlex.split(line.split("=", 1)[1])[0]
   subprocess.run(["aws", "ssm", "put-parameter", "--name", "/metamorph/api/curators", "--type", "SecureString",
                   "--overwrite", "--value", value], check=True, stdout=subprocess.DEVNULL)
   EOF
   ```
   For new accounts instead, make each hash with `docker compose run --rm api curator hash-password`.
3. **The database stack.** It takes 10–15 minutes. Check the newest PostgreSQL 16 first, and pass it if it differs from the template's `16.15`:
   ```bash
   aws rds describe-db-engine-versions --engine postgres --engine-version 16 --query 'DBEngineVersions[-1].EngineVersion'
   deploy database                    # or: deploy database --parameter-overrides EngineVersion=16.x
   ```
4. **The database URLs,** from the host the stack wrote:
   ```bash
   DB_HOST=$(setting /metamorph/database/host)
   PW=$(setting /metamorph/database/master-password) BI_PW=$(setting /metamorph/database/bi-password)
   secret /metamorph/platform/database-url "postgresql://metamorph:$PW@$DB_HOST:5432/metamorph"
   secret /metamorph/airflow/database-url "postgresql+psycopg2://metamorph:$PW@$DB_HOST:5432/airflow"
   secret /metamorph/bi/database-url "postgresql+psycopg://bi:$BI_PW@$DB_HOST:5432/bi"
   unset PW BI_PW
   ```

## Phase 3: the images

1. **Build and push the arm64 images from the Mac:**
   ```bash
   TAG=$(date -u +%Y%m%d-%H%M) deploy/aws/push-images.sh      # prints "pushed with tag …"
   TAG=<that tag>
   ```
   The first push uploads about 3 GB. Uploads into AWS are free.
2. **The MinerU stack.** It creates the GPU Auto Scaling group, which launches one instance into the warm pool. That instance boots once and stops. The stack also creates the service (desired count 0) and the window's schedules:
   ```bash
   deploy mineru
   ```
3. **Upload the platform's source** for the MinerU build:
   ```bash
   OPS=metamorph-ops-$ACCOUNT
   git archive --format=tar.gz --prefix=Metamorph-Knowledge-Platform/ HEAD \
     | aws s3 cp - "s3://$OPS/transfer/source/Metamorph-Knowledge-Platform.tgz"
   ```
4. **Build MinerU's image on the GPU instance.** It is x86-64 and 19.6 GB, so it is built where it runs. The build also leaves it in the instance's Docker cache. Hold the instance in service while you work:
   ```bash
   aws autoscaling update-auto-scaling-group --auto-scaling-group-name metamorph-gpu --min-size 1
   sleep 120
   GPU=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names metamorph-gpu \
           --query 'AutoScalingGroups[0].Instances[?LifecycleState==`InService`].InstanceId | [0]' --output text)
   aws ssm start-session --target "$GPU"
   ```
   On the instance:
   ```bash
   sudo -i
   nvidia-smi --query-gpu=name,driver_version --format=csv,noheader      # NVIDIA A10G, and a driver of 580 or newer
   REGION=ap-southeast-3 ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
   mkdir -p /root/build && cd /root/build
   aws s3 cp "s3://metamorph-ops-$ACCOUNT/transfer/source/Metamorph-Knowledge-Platform.tgz" - | tar -xzf -
   docker build -t "$REGISTRY/metamorph/mineru:4.0.12" Metamorph-Knowledge-Platform/docker/mineru   # 30–60 minutes
   aws ecr get-login-password --region $REGION | docker login -u AWS --password-stdin "$REGISTRY"
   docker push "$REGISTRY/metamorph/mineru:4.0.12"
   docker builder prune -af && df -h /
   exit; exit
   ```
   **The driver must be 580 or newer,** because MinerU's vLLM build needs CUDA 13. If the ECS GPU AMI's driver is older, stop here: see [What can go wrong](#what-can-go-wrong).

   Then let the instance go back to the warm pool. Within about 15 minutes, ECS scales the group in and the instance stops with the image still on its disk:
   ```bash
   aws autoscaling update-auto-scaling-group --auto-scaling-group-name metamorph-gpu --min-size 0
   ```

## Phase 4: move the data from the Mac

This is the cut-over. **From here until Phase 7 is done, nobody curates on the Mac**, because their changes wouldn't come across. The DAGs are paused on the Mac, so no connector writes either. First, note the counts on the Mac's overview page (published, held, review queues, gaps). Phase 7 compares against them.

1. **The task definitions,** including `metamorph-ops`:
   ```bash
   deploy jobs --parameter-overrides PlatformTag=$TAG OjkTag=$TAG BpkTag=$TAG BiTag=$TAG DsnTag=$TAG
   ```
2. **Two helpers** for one-off tasks. Each one runs a task, waits for it to finish, and prints its log and exit code:
   ```bash
   NET="awsvpcConfiguration={subnets=[$(setting /metamorph/airflow/ecs-subnets)],securityGroups=[$(setting /metamorph/airflow/ecs-security-group)],assignPublicIp=ENABLED}"
   run_task() {  # family (without metamorph-), then the command, one word per argument
     local overrides id
     overrides=$(python3 -c 'import json, sys; print(json.dumps({"containerOverrides": [{"name": "main", "command": sys.argv[1:]}]}))' "${@:2}")
     id=$(aws ecs run-task --cluster metamorph --launch-type FARGATE --task-definition "metamorph-$1" \
            --network-configuration "$NET" --overrides "$overrides" --query 'tasks[0].taskArn' --output text)
     id=${id##*/}; echo "task $id"
     until aws ecs wait tasks-stopped --cluster metamorph --tasks "$id" 2>/dev/null; do :; done
     aws logs tail /metamorph --log-stream-names "metamorph-$1/main/$id" --since 1d
     aws ecs describe-tasks --cluster metamorph --tasks "$id" --query 'tasks[0].containers[0].[exitCode,reason]' --output text
   }
   ```
3. **The databases,** dumped on the Mac: the platform's and BI's own. Airflow's isn't moved. It starts fresh on RDS, with every DAG paused.
   ```bash
   mkdir -p ~/metamorph-deploy
   docker exec metamorph-postgres-1 pg_dump -U metamorph -Fc metamorph > ~/metamorph-deploy/metamorph.dump
   docker exec metamorph-postgres-1 pg_dump -U metamorph -Fc bi        > ~/metamorph-deploy/bi.dump
   ```
4. **Restore them through a tunnel.** RDS takes no connection from outside the VPC, so an ops task is the way in. Start one that waits for three hours:
   ```bash
   aws ecs run-task --cluster metamorph --launch-type FARGATE --task-definition metamorph-ops \
     --network-configuration "$NET" --enable-execute-command \
     --overrides '{"containerOverrides":[{"name":"main","command":["sleep 10800"]}]}' --query 'tasks[0].taskArn'
   sleep 60; deploy/aws/tunnel.sh ops 15432 "$DB_HOST:5432"          # leave it running; a second terminal for the rest
   ```
   In the second terminal, run the Phase 0 shell lines again, then:
   ```bash
   export PGPASSWORD=$(setting /metamorph/database/master-password) BI_PW=$(setting /metamorph/database/bi-password)
   pg() { docker run --rm -i -e PGPASSWORD -e PGHOST=host.docker.internal -e PGPORT=15432 -e PGUSER=metamorph \
            -v ~/metamorph-deploy:/dumps:ro postgres:16 "$@"; }
   pg psql -d metamorph -v ON_ERROR_STOP=1 <<SQL
   CREATE ROLE bi LOGIN PASSWORD '$BI_PW';
   GRANT bi TO metamorph;
   CREATE DATABASE bi OWNER bi;
   CREATE DATABASE airflow;
   SQL
   pg pg_restore -d metamorph --no-owner --no-privileges /dumps/metamorph.dump
   pg pg_restore -d bi --no-owner --no-privileges --role=bi /dumps/bi.dump
   pg psql -d metamorph -Atc "select count(*) from published.document"      # 2,561 on 2026-10-23
   unset PGPASSWORD BI_PW
   ```
   The dump goes through Session Manager, which is slow: allow 10–20 minutes. Stop the tunnel with Ctrl-C, then stop the ops task: `aws ecs stop-task --cluster metamorph --task <its ARN>`.
5. **Migrations.** This is a no-op at migration 15, but it proves the platform's task reaches RDS:
   ```bash
   run_task platform db migrate
   ```
6. **The blobs, from SeaweedFS straight to S3.** Their keys (`blobs/<2>/<sha256>`) are content addresses, so they stay valid:
   ```bash
   AWS_ACCESS_KEY_ID=metamorph AWS_SECRET_ACCESS_KEY=metamorph-dev-secret \
     aws s3 sync s3://metamorph-blobs ~/metamorph-deploy/blobs --endpoint-url http://localhost:8333 --region us-east-1
   aws s3 sync ~/metamorph-deploy/blobs "s3://metamorph-blobs-$ACCOUNT/"
   aws s3 ls "s3://metamorph-blobs-$ACCOUNT/" --recursive --summarize | tail -2   # 13,455 objects, 2.99 GB (2026-10-23)
   ```
7. **The connectors' data,** with their stores, PDFs and **MinerU caches**, into EFS. The old bundles (`exports/`) are left out. The caches are the one thing here that costs money to rebuild: every reading in them would have to be paid for on the GPU again.
   ```bash
   (cd .. && COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata --exclude='.DS_Store' --exclude='*/data/exports' \
      -czf ~/metamorph-deploy/connector-data.tgz {BI,BPK,OJK,DSN-MUI}-Source-Connector/data)
   tar -tzf ~/metamorph-deploy/connector-data.tgz | grep -c mineru-cache/                # the readings are in it
   aws s3 cp ~/metamorph-deploy/connector-data.tgz "s3://$OPS/transfer/connector-data.tgz"
   run_task ops "$(cat <<'EOF'
   python -c "import boto3, os, shutil, sys; s3 = boto3.client('s3'); shutil.copyfileobj(s3.get_object(Bucket=os.environ['OPS_BUCKET'], Key='transfer/connector-data.tgz')['Body'], sys.stdout.buffer)" \
     | tar -xzf - --no-same-owner --no-same-permissions -C /workspace && du -sh /workspace/*/data
   EOF
   )"
   ```
   **Pass:** it prints four `data` directories, with the same sizes as on the Mac (`du -sh ../*-Source-Connector/data`), and exits `0`. Each connector's directory lands at the path its task mounts. The `transfer/` copy expires after 14 days.

## Phase 5: the services

1. **The API:**
   ```bash
   deploy api --parameter-overrides PlatformTag=$TAG
   ```
2. **The certificate.** Request it, add its validation record to your DNS, and wait:
   ```bash
   DOMAIN=curation.<your-domain>
   CERT=$(aws acm request-certificate --domain-name "$DOMAIN" --validation-method DNS --query CertificateArn --output text)
   sleep 10; aws acm describe-certificate --certificate-arn "$CERT" \
     --query 'Certificate.DomainValidationOptions[0].ResourceRecord' --output table      # add this CNAME
   aws acm wait certificate-validated --certificate-arn "$CERT"
   ```
3. **The web app,** and its host name:
   ```bash
   deploy web --parameter-overrides WebTag=$TAG CertificateArn="$CERT"
   aws cloudformation describe-stacks --stack-name metamorph-web \
     --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerDns'].OutputValue" --output text
   ```
   Add a CNAME from `$DOMAIN` to that name.
4. **Browser uploads.** Set the blobs bucket's CORS so the app's origin may upload through signed links. It answers `already there` for the bucket, as expected:
   ```bash
   run_task platform storage init --upload-origin "https://$DOMAIN"
   ```
5. **Airflow.** Its first start migrates its database and creates `admin`:
   ```bash
   deploy airflow --parameter-overrides AirflowTag=$TAG
   ```
   For failure alerts, add the webhook first, then redeploy with it on: `secret /metamorph/airflow/alert-webhook-url https://hooks…` and `deploy airflow --parameter-overrides AlertWebhook=yes`.

## Phase 6: MinerU and its window

1. **Open the window by hand:**
   ```bash
   aws ecs update-service --cluster metamorph --service mineru --desired-count 1 >/dev/null
   until [ "$(aws ecs describe-services --cluster metamorph --services mineru --query 'services[0].runningCount')" = 1 ]; do sleep 30; done
   ```
   That takes 5–10 minutes: ECS scales the group out, the instance leaves the warm pool, and the models load.
2. **Read two files through it** from a BPK task, which holds `mineru_check.py`. They are the 50-page scan and the 43-page born-digital regulation that were timed on the Mac and in step 9:
   ```bash
   run_task bpk-connector sh -c 'python -u /workspace/Metamorph-Knowledge-Platform/packages/metamorph-pdf-text/scripts/mineru_check.py \
     data/raw/79/79dd6317b3b0a647a61012a60ce574f98075577fc8f7a591108a4cc138ca95c0 \
     data/raw/a5/a50d9ee2f39bd2e59386e8b52dfc415b4bfaf425c75561bb1346dd29b9d37241'
   ```
   **Pass:** it prints `version`, `tiers` and four `models` lines, then the timings, and exits `0`. MinerU's task must still be running afterwards. If it stopped with exit code 137 (`aws ecs describe-tasks`), 16 GiB was too little: [What can go wrong](#what-can-go-wrong).
3. **Close it:** `aws ecs update-service --cluster metamorph --service mineru --desired-count 0`. From now on, the schedules open it at 00:30 UTC and close it at 03:15, or at 04:30 on the 1st.

## Phase 7: check, then go live

**Go when every line passes:**

| Check | How |
|---|---|
| The curation app works over HTTPS | Sign in. Open a document, read a text, open its PDF (a signed S3 link), and see the footer "Text extraction by MinerU" |
| The registry came across whole | The overview's counts (published, held, review queues, gaps) match the ones you noted on the Mac in Phase 4 |
| Uploads work | **Add Document** with a small PDF: it goes from the browser to S3 |
| Airflow is up, every DAG paused | `deploy/aws/tunnel.sh airflow 18080 8080`, then http://localhost:18080. Sign in as `admin` with `setting /metamorph/airflow/admin-password` |
| One ingest end to end | With MinerU's window open (Phase 6 step 1), unpause `ingest_dsn_fatwa` and trigger it. The smallest connector. `registry_build` follows its load |
| Nothing is open that shouldn't be | `aws ec2 describe-security-groups --filters Name=group-name,Values='*metamorph*' --query 'SecurityGroups[].IpPermissions[].IpRanges[].CidrIp'` shows `0.0.0.0/0` twice only: the load balancer's 80 and 443 |

**Then go live:**
1. **Unpause the DAGs** in Airflow's UI: the five `ingest_*` DAGs, `registry_build` and `health`.
2. **Retire the Mac as the live stack.** Keep its DAGs paused for good: connector state now lives in EFS, and two schedulers writing two copies of it would diverge. The Mac stays the development stack. The deployed connectors never use the Mac's MinerU, whose vision model is a development-only GGUF conversion.
3. **After the first week,** check the bill in Cost Explorer, grouped by service. The EC2 line, which includes the GPU, should be about the window's hours × $1.408.

## Operating it

**Deploying a change.** Commit, push the images that changed under a new tag, and deploy the stacks that use them. Other services keep their tags.

| Changed | Push | Deploy |
|---|---|---|
| The web app | `TAG=… deploy/aws/push-images.sh curation-web` | `deploy web --parameter-overrides WebTag=$TAG` |
| The platform | `… push-images.sh platform` | `deploy api --parameter-overrides PlatformTag=$TAG`, then `deploy jobs --parameter-overrides PlatformTag=$TAG`, then `run_task platform db migrate` if there is a new migration |
| A connector | `… push-images.sh bpk-connector` | `deploy jobs --parameter-overrides BpkTag=$TAG` |
| `packages/` (contract, pdf-text) | all four connectors and the platform | `deploy jobs` with every tag, then `deploy api` |
| The DAGs | `… push-images.sh airflow` | `deploy airflow --parameter-overrides AirflowTag=$TAG` |

`aws cloudformation deploy` keeps a parameter you don't pass as it was. A deployment that fails its health checks rolls back by itself, thanks to the circuit breaker on `web`, `api` and `airflow`. To return to an older version, deploy the old tag.

**Changing MinerU's image** changes how new files are read. Keep `MINERU_VERSION`, `TRANSLATION`, the tier policy and the server's options as they are, or every cached reading becomes a miss ([deployment-architecture.md](deployment-architecture.md#step-9-on-sagemaker-ai-and-the-deployed-architecture)).

**A backlog for MinerU** (many new files, or a connector that fell behind): open the window by hand (Phase 6 step 1) and trigger the DAG. Close it after the run. Readings made before a close are cached, so an interrupted run carries on in the next window.

**Rolling back the PDF engine:** `aws ssm put-parameter --name /metamorph/connectors/pdf-engine --value pymupdf --overwrite`. The next connector runs use PyMuPDF, with texts byte-identical to those from before MinerU. MinerU's readings stay in the caches.

**Logs:**
- A service: `aws logs tail /metamorph --follow --log-stream-name-prefix metamorph-api`, or `metamorph-web`, `metamorph-airflow`, `metamorph-mineru`.
- A DAG task: its log is in Airflow's UI. Airflow copies it from CloudWatch as the task runs.

**Restoring:**

| What is lost | From |
|---|---|
| The database, or a mistaken change | RDS point-in-time restore, to any second of the last 7 days, into a new instance. Point the URLs in Parameter Store at it and restart the services |
| A connector's data or MinerU cache | AWS Backup's daily recovery point of the EFS file system (35 days), restored into its own directory, then copied back with a `metamorph-ops` task |
| The blobs | The bucket keeps every blob, and nothing deletes one. It is retained even if the stack is deleted |
| The settings | Parameter Store keeps each parameter's history: `aws ssm get-parameter-history --name … --with-decryption` |

**Rolling back to the Mac:** the Mac's stack and data stay as they were at the cut-over, until you delete them. To go back:
1. Pause the AWS DAGs.
2. Dump RDS through the tunnel, and restore it on the Mac.
3. Copy EFS's data back with a `metamorph-ops` task, through `transfer/`.
4. Unpause the Mac's DAGs.

**Taking it down,** in reverse order:
1. Delete the stacks: `metamorph-mineru`, `-airflow`, `-web`, `-api`, `-jobs`.
2. The database: turn off its deletion protection, then delete `metamorph-database`. A final snapshot is kept.
3. Empty the ECR repositories and the ops bucket, then delete `metamorph-foundation`.
4. Delete the EFS file system and the blobs bucket by hand: they are kept on purpose.

## What can go wrong

| Risk | What happens | What to do |
|---|---|---|
| Your access is SageMaker only | `CreateStack` is refused | Phase 0 step 1: the [appendix](#appendix-the-operators-permissions)'s policy |
| No GPU quota | The Auto Scaling group's activity shows `VcpuLimitExceeded` | Phase 0 step 2, days ahead |
| No G5 capacity | The group's activity shows `InsufficientInstanceCapacity` | It tries every subnet's zone by itself. If all three are out, wait or use the g5.2xlarge |
| The ECS GPU AMI's NVIDIA driver is older than 580 | MinerU's task fails to start vLLM: it needs CUDA 13 | Build an AMI from the GPU AMI with the `nvidia-580` driver, and pass its ID as the mineru stack's `GpuImageId` |
| The g5.xlarge runs out of RAM | MinerU's task stops with exit code 137 during a long scan | `deploy mineru --parameter-overrides InstanceType=g5.2xlarge`, about $0.29 an hour more. Then cycle the warm instance: set the group's `--min-size 1`, then `0` |
| MinerU is down during a window | Connector tasks fail with `ExtractionUnavailable`, then retry 15 minutes later | By design, nothing switches engines silently. Open the window by hand and clear the failed tasks in Airflow |
| A run outlasts the window | MinerU stops mid-read, and the task and its retry fail | Its readings so far are cached, so the next window carries on. For a known backlog, see Operating it |
| A task can't read its settings | It stops with `ResourceInitializationError … ssm` | A parameter it names is missing: the table in [Settings](#settings-in-parameter-store) |
| The first stack fails on a service-linked role | `CreateCluster` or `CreateLoadBalancer` is refused | `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com`, likewise for `autoscaling`, `elasticloadbalancing`, `rds`, `elasticfilesystem` and `backup`, then deploy again |
| No certificate | `aws acm wait` times out | The validation CNAME must be exactly as ACM gave it |
| Airflow restarts | Running DAG tasks are lost. Their ECS tasks finish, but Airflow marks them failed and retries | Expected on a deployment. Deploy Airflow outside the window |
| A secret leaks | | Secrets exist only in Parameter Store, encrypted, and reach a container at its start. Rotate: `secret … <new value>`, then restart the services that read it |

## Appendix: the operator's permissions

For the person following this guide, if they aren't an administrator. AWS's managed `PowerUserAccess` covers every service here but IAM. Add this inline policy for the roles the stacks create, all named `metamorph-*`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow",
     "Action": ["iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UpdateAssumeRolePolicy",
                "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
                "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PassRole",
                "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy", "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
                "iam:ListPolicyVersions",
                "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile",
                "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile"],
     "Resource": ["arn:aws:iam::*:role/metamorph-*", "arn:aws:iam::*:policy/metamorph-*",
                  "arn:aws:iam::*:instance-profile/metamorph-*"]},
    {"Effect": "Allow", "Action": "iam:CreateServiceLinkedRole", "Resource": "*"}
  ]
}
```

The roles the tasks get are in the templates, each limited to what its service does:
- **Every task:** `metamorph-task-execution` pulls images, writes logs, and reads `/metamorph/*` only.
- **The platform's tasks and the API:** `metamorph-platform` reads and writes the blobs bucket, without delete.
- **Airflow:** `metamorph-airflow` may run only `metamorph-*` task definitions in this cluster.
- **The GPU instance:** `metamorph-gpu-instance` reads the source archive and pushes MinerU's image only.
