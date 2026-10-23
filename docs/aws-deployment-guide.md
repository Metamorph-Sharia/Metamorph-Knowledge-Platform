# Deploying Metamorph on AWS (Jakarta): the core first

**Date:** 2026-10-23 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Account access:** the `Project3Learner` role, as it is today · **Status:** designed and written; nothing created on AWS yet. Checks so far:
- the templates pass `cfn-lint` and CloudFormation's own `validate-template`;
- the Aurora version and the existing role were checked in the account;
- the stacks' layering is tested.

**Files:** [`deploy/aws/`](../deploy/aws)

This guide deploys **the core:** the curation web app, the curation API and the database. It uses only the access the account has today. **Ingestion** (Airflow, the four connectors, MinerU) is a second layer, already designed in [`deploy/aws/ingestion/`](../deploy/aws/ingestion/README.md). It plugs into the core without changing it, once the account can create IAM roles, use EFS and Cloud Map, and run a GPU.

## Contents

1. [The design](#the-design)
2. [Why it fits today's access](#why-it-fits-todays-access)
3. [How ingestion plugs in later](#how-ingestion-plugs-in-later)
4. [Settings in Parameter Store](#settings-in-parameter-store)
5. [What it costs](#what-it-costs)
6. [Phase 0: before you start](#phase-0-before-you-start)
7. [Phase 1: the foundation and the secrets](#phase-1-the-foundation-and-the-secrets)
8. [Phase 2: the database](#phase-2-the-database)
9. [Phase 3: the images](#phase-3-the-images)
10. [Phase 4: move the data from the Mac](#phase-4-move-the-data-from-the-mac)
11. [Phase 5: the API and the web app](#phase-5-the-api-and-the-web-app)
12. [Phase 6: check, then go live](#phase-6-check-then-go-live)
13. [Operating it](#operating-it)
14. [What can go wrong](#what-can-go-wrong)

## The design

```
 Curators ── HTTPS ──► public load balancer (ACM certificate) ──► web   Fargate ARM, ECS service "web"
                                                                    │ http://<internal load balancer>   (/metamorph/web/api-url)
                                                                    ▼
                                   internal load balancer, from the web app only ──► api   Fargate ARM, ECS service "api" ──► S3 blobs
                                                                                      │
 Aurora Serverless v2, PostgreSQL 16 (pauses at 0 ACU when idle) ◄────────────────────┘
   one-off tasks: metamorph-cli (migrations, build, health) · metamorph-dbops (restores from the operations bucket)
 Parameter Store /metamorph/* · CloudWatch Logs /metamorph · ECR metamorph/platform, metamorph/curation-web
```

| Piece | Runs as | Stack | Stop it / start it |
|---|---|---|---|
| Curation web app | ECS service `web`: Fargate ARM, 0.25 vCPU, 0.5 GB | `metamorph-web` | `aws ecs update-service --cluster metamorph --service web --desired-count 0` / `1` |
| Curation API | ECS service `api`: Fargate ARM, 0.25 vCPU, 1 GB | `metamorph-api` | the same, `--service api` |
| `metamorph` commands | task definition `metamorph-cli` | `metamorph-api` | runs once and stops: `db migrate`, `build`, `health` |
| Database | Aurora cluster `metamorph`, one `db.serverless` writer | `metamorph-database` | pauses by itself after 15 idle minutes, and wakes on the next connection |
| Restores | task definition `metamorph-dbops` | `metamorph-database` | runs once and stops |
| Cluster, security groups, buckets, image repositories | | `metamorph-foundation` | |

A desired count set with the CLI stays until the next update of that service's stack. To keep a service stopped across updates, deploy its stack with `DesiredCount=0`.

**The choices, and why:**

| Choice | Why | Rejected |
|---|---|---|
| **Fargate on Graviton (ARM64)** | No servers. Billed by the second, and 20% cheaper than x86 in Jakarta. The Mac is arm64, so the images already build for it | ECS on EC2: a server to patch again |
| **Each service its own stack** | Each stack creates, updates or deletes one service and nothing else. Changes are reviewable and reversible | Console clicks: nothing records what was made |
| **Aurora Serverless v2, minimum 0 ACU** | The account allows only Aurora Serverless v2. At 0 ACU it pauses when no curator works, and you pay for storage only | A minimum of 0.5 ACU: about $73 a month, even at night |
| **An internal load balancer in front of the API** | A stable private address, reachable only from the web app's security group. The API stays off the internet, as on the Mac | **Cloud Map:** not allowed in this account. **The web app and API in one task:** saves about $19 a month, but one can't be stopped or deployed without the other |
| **Public subnets with a public IP per task, no NAT gateway** | Tasks need outbound access to ECR and Parameter Store. A public IPv4 costs $3.65 a month. Inbound, everything but the public load balancer is closed | **NAT gateway:** $43 a month plus data |
| **Parameter Store for every setting** | Free and encrypted, and ECS reads it into each container at start | **Secrets Manager:** $0.40 per secret a month |

## Why it fits today's access

The `Project3Learner` role can't create IAM roles, and every role in the account has the same `LearnerLimits` ceiling. The core works within that:

| It needs | Today's access gives |
|---|---|
| A role for ECS to start tasks | `Project3EcsTaskExecutionRole`, already there: it pulls images, writes logs, and reads Parameter Store and Secrets Manager |
| A role for the API's containers, with S3 | **The same role.** It has no S3 permission of its own, so the buckets' policies grant it: your role may set bucket policies, and in one account a bucket policy is enough |
| PostgreSQL | Aurora Serverless v2 PostgreSQL, the only engine the account allows. The platform needs nothing Aurora lacks: the Mac's dump uses no extension |
| A private address for the API | An internal load balancer (`elasticloadbalancing:*`) |
| HTTPS | ACM and Route 53, both allowed |
| Resources marked as the project's | Every stack is deployed with the tag `Owner=project3`, which the account's rules accept, and they also protect resources tagged that way |

**The trade-off:** the API runs as the execution role, so it could read every `/metamorph/` parameter, not only its own four. A dedicated role, when the account allows one, replaces it. That means deploying the foundation with a new `AppRoleArn` and adding the role to `BucketRoleArns`, with no other change.

**What doesn't fit, and waits for the ingestion layer:** Airflow running ECS tasks (it needs a role of its own), EFS, Cloud Map, and a GPU instance.

## How ingestion plugs in later

The core never refers to ingestion. Ingestion refers only to the core's exports, and `tests/test_deploy_layers.py` checks both rules.

| Core stack | Exports for later layers |
|---|---|
| `metamorph-foundation` | the VPC, the subnets, the cluster, the log group, the security groups (including the database's), the buckets, the registry, the execution role and the app role |
| `metamorph-database` | the database host, plus `/metamorph/database/host` in Parameter Store |

When access arrives, [`deploy/aws/ingestion/README.md`](../deploy/aws/ingestion/README.md) adds the layer. It deploys a `metamorph-ingestion-shared` stack, then the jobs, Airflow and MinerU stacks:
- **`metamorph-ingestion-shared`** opens its own way into the core's database: rules on the core's database security group, created by the ingestion stack. It creates its own repositories and roles, whose own policies give them S3.
- **The jobs, Airflow and MinerU stacks** follow.

No core stack is redeployed.

**Until then:**
- **The registry on AWS doesn't grow.** No connector runs there, and the Mac can't reach Aurora.
- **Curators work on AWS.** A curator's change is published by the next `metamorph build`, which the ingestion layer would run after every load. For now, run it by hand: [Operating it](#operating-it).
- **The Mac stops being the live system at the cut-over.** Keep its DAGs paused. A Mac that went on ingesting would diverge from AWS, and its new documents would have to be moved again.

## Settings in Parameter Store

Every value a container reads from its environment is a parameter under `/metamorph/`, and the task definitions name them.

| Parameter | Type | Written by | Read by |
|---|---|---|---|
| `/metamorph/database/master-password` | SecureString | you, Phase 1 | Aurora (the database stack), `metamorph-dbops` |
| `/metamorph/database/bi-password` | SecureString | you, Phase 1 | `metamorph-dbops`, when it creates BI's role (BI's database is kept for the BI connector) |
| `/metamorph/database/host` | String | the database stack | `metamorph-dbops`; you, to build the URL below |
| `/metamorph/platform/database-url` | SecureString | you, Phase 2 | the API, `metamorph-cli` |
| `/metamorph/platform/s3-bucket` | String | the foundation stack | the API, `metamorph-cli` |
| `/metamorph/api/curators` | SecureString | you, Phase 1 | the API |
| `/metamorph/api/web-secret` | SecureString | you, Phase 1 | the API |
| `/metamorph/web/api-url` | String | the API stack (its internal load balancer) | the web app |
| `/metamorph/ops/bucket` | String | the foundation stack | `metamorph-dbops` |

CloudFormation can't create SecureStrings, so you write the secret ones with the CLI. The stacks write the String ones for what they create. To change a setting, use `put-parameter --overwrite`. A one-off task reads it at its next start; a service needs a restart, with `aws ecs update-service --cluster metamorph --service api --force-new-deployment`.

## What it costs

These are Jakarta on-demand prices from AWS's public price list files, read on 2026-10-23.

| Item | Rate | Monthly |
|---|---|---:|
| Web app: 0.25 vCPU, 0.5 GB, Fargate ARM | $0.04045 per vCPU-hour, $0.00442 per GB-hour | $9.00 |
| API: 0.25 vCPU, 1 GB | | $10.61 |
| Public load balancer, and the API's internal one | $0.0252 an hour each, plus a few LCUs | about $38 |
| Public IPv4: the two tasks, and the public load balancer's two | $0.005 an hour each | $14.60 |
| Aurora: 0.5 ACU while curators work (about 9 hours on weekdays, plus 15 minutes before each pause), paused otherwise | $0.20 per ACU-hour | about $21 |
| Aurora storage (about 3 GB) and I/O. Backups up to the database's size are free | $0.11 per GB-month, $0.22 per million I/Os | about $1.50 |
| ECR, CloudWatch Logs (30 days), S3 (3 GB of blobs) | | about $1 |
| One-off tasks (`metamorph-cli`, `metamorph-dbops`) | billed by the second while they run | cents |
| **Total** | | **about $96** |

**What moves the total:**
- **Aurora is the variable.** Used around the clock, it stays at 0.5 ACU or more: about $73 instead of $21. A heavy query scales it up for its duration only, up to `MaxCapacity`, 4 ACUs.
- **The web app and API only in working hours:** an Application Auto Scaling scheduled action, which the account allows, sets each service's count to 0 at night and 1 in the morning. That saves about $12 a month, and Aurora then always pauses at night.
- **The ingestion layer adds its own costs later.** Airflow keeps a connection open, so Aurora would no longer pause: plan on the 0.5 ACU floor once it runs. The [ingestion README](../deploy/aws/ingestion/README.md) has its estimate.

## Phase 0: before you start

1. **The tools on the Mac:** the AWS CLI v2, signed in with the `Project3Learner` role (`aws sts get-caller-identity`), and Docker Desktop.
2. **The curation app's host name,** for example `curation.<your-domain>`. You must be able to add CNAME records in its DNS, in Route 53 or elsewhere.
3. **Commit and push** the platform and the web app. Images are built from the working trees, and a tag should always name code that is in git.
4. **A shell with these lines,** for every later command, run from `~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform`:
   ```bash
   export AWS_REGION=ap-southeast-3
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   ROLE=arn:aws:iam::$ACCOUNT:role/Project3EcsTaskExecutionRole
   DOMAIN=curation.<your-domain>
   setting() { aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text; }
   secret() { aws ssm put-parameter --name "$1" --type SecureString --value "$2" --overwrite >/dev/null; }
   deploy() { aws cloudformation deploy --stack-name "metamorph-${1//\//-}" --template-file "deploy/aws/$1.yaml" \
                --tags Owner=project3 --no-fail-on-empty-changeset "${@:2}"; }
   exported() { aws cloudformation list-exports --query "Exports[?Name=='$1'].Value" --output text; }
   ```

## Phase 1: the foundation and the secrets

1. **The default VPC and its three subnets,** one per Availability Zone:
   ```bash
   VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
   SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
               --query 'Subnets[].SubnetId' --output text | tr '\t' ',')
   echo "$VPC $SUBNETS"                 # three subnet IDs
   ```
2. **The foundation stack:** the cluster, the security groups, the log group, the buckets with their policies and CORS, the two image repositories, and the wiring parameters. The existing role is the execution role, the app role and the one bucket principal:
   ```bash
   deploy foundation --parameter-overrides VpcId="$VPC" Subnets="$SUBNETS" \
     ExecutionRoleArn="$ROLE" AppRoleArn="$ROLE" BucketRoleArns="$ROLE" AppOrigin="https://$DOMAIN"
   ```
3. **The secrets,** each generated here and never shown:
   ```bash
   secret /metamorph/database/master-password "$(openssl rand -hex 24)"
   secret /metamorph/database/bi-password "$(openssl rand -hex 24)"
   secret /metamorph/api/web-secret "$(openssl rand -hex 32)"
   ```
4. **The curators' accounts,** copied from the Mac's `.env` without being printed:
   ```bash
   python3 - <<'EOF'
   import pathlib, shlex, subprocess
   line = next(l for l in pathlib.Path(".env").read_text().splitlines() if l.startswith("METAMORPH_CURATORS="))
   value = shlex.split(line.split("=", 1)[1])[0]
   subprocess.run(["aws", "ssm", "put-parameter", "--name", "/metamorph/api/curators", "--type", "SecureString",
                   "--overwrite", "--value", value], check=True, stdout=subprocess.DEVNULL)
   EOF
   ```
5. **The budget,** with email alerts at 50%, 80% and 100%. Budgets are allowed through the CLI:
   ```bash
   EMAIL=you@example.com LIMIT=120
   python3 -c "import json; print(json.dumps([{'Notification': {'NotificationType': 'ACTUAL', 'ComparisonOperator': 'GREATER_THAN', 'Threshold': t}, 'Subscribers': [{'SubscriptionType': 'EMAIL', 'Address': '$EMAIL'}]} for t in (50, 80, 100)]))" > /tmp/budget-alerts.json
   aws budgets create-budget --account-id "$ACCOUNT" \
     --budget "{\"BudgetName\":\"metamorph\",\"BudgetLimit\":{\"Amount\":\"$LIMIT\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
     --notifications-with-subscribers file:///tmp/budget-alerts.json
   ```

## Phase 2: the database

1. **The database stack:** the Aurora cluster and its writer, plus the `metamorph-dbops` task. It takes 10–15 minutes. The template's `16.15` was the newest PostgreSQL 16 in Jakarta on 2026-10-23.
   ```bash
   deploy database
   ```
2. **The platform's database URL,** from the host the stack wrote:
   ```bash
   DB_HOST=$(setting /metamorph/database/host)
   secret /metamorph/platform/database-url "postgresql://metamorph:$(setting /metamorph/database/master-password)@$DB_HOST:5432/metamorph"
   ```

## Phase 3: the images

Build both arm64 images on the Mac and push them to ECR. The first push uploads about 400 MB, and uploads into AWS are free.

```bash
TAG=$(date -u +%Y%m%d-%H%M) deploy/aws/push-images.sh      # prints "pushed with tag …"
TAG=<that tag>
```

## Phase 4: move the data from the Mac

This is the cut-over. **From here on, nobody curates on the Mac**, because their changes wouldn't come across. Keep the Mac's DAGs paused. First, note the counts on the Mac's overview page (published, held, review queues, gaps): Phase 6 compares against them.

1. **The API stack,** with its service stopped for now. It also defines `metamorph-cli`, which the next steps use:
   ```bash
   deploy api --parameter-overrides PlatformTag=$TAG DesiredCount=0
   ```
2. **A helper for one-off tasks.** It runs a task, waits for it to finish, and prints its log and exit code:
   ```bash
   run_task() {  # family (without metamorph-), the export of its security group, then the command, one word per argument
     local net overrides id
     net="awsvpcConfiguration={subnets=[$(exported metamorph-subnets)],securityGroups=[$(exported "$2")],assignPublicIp=ENABLED}"
     overrides=$(python3 -c 'import json, sys; print(json.dumps({"containerOverrides": [{"name": "main", "command": sys.argv[1:]}]}))' "${@:3}")
     id=$(aws ecs run-task --cluster metamorph --launch-type FARGATE --task-definition "metamorph-$1" \
            --network-configuration "$net" --overrides "$overrides" --query 'tasks[0].taskArn' --output text)
     id=${id##*/}; echo "task $id"
     until aws ecs wait tasks-stopped --cluster metamorph --tasks "$id" 2>/dev/null; do :; done
     aws logs tail /metamorph --log-stream-name-prefix "metamorph-$1/" --since 1h | grep "$id"
     aws ecs describe-tasks --cluster metamorph --tasks "$id" \
       --query 'tasks[0].containers[?name==`main`].[exitCode,reason]' --output text
   }
   ```
3. **The databases:** the platform's and BI's own, dumped on the Mac and put in the operations bucket. Its `transfer/` copies expire after 14 days.
   ```bash
   mkdir -p ~/metamorph-deploy
   docker exec metamorph-postgres-1 pg_dump -U metamorph -Fc metamorph > ~/metamorph-deploy/metamorph.dump
   docker exec metamorph-postgres-1 pg_dump -U metamorph -Fc bi        > ~/metamorph-deploy/bi.dump
   for f in metamorph bi; do
     aws s3 cp ~/metamorph-deploy/$f.dump "s3://metamorph-ops-$ACCOUNT/transfer/database/$f.dump"
   done
   ```
4. **Restore them in the VPC.** `metamorph-dbops` copies `transfer/database/` into its `/work`, then runs this in its PostgreSQL container, signed in as the master user. It wakes Aurora on its first connection.
   ```bash
   run_task dbops metamorph-sg-database-ops "$(cat <<'EOF'
   psql -v ON_ERROR_STOP=1 -c "CREATE ROLE bi LOGIN PASSWORD '$BI_PASSWORD'" -c 'GRANT bi TO metamorph' \
        -c 'CREATE DATABASE bi OWNER bi' \
     && { pg_restore -d metamorph --no-owner --no-privileges metamorph.dump
          pg_restore -d bi --no-owner --no-privileges --role=bi bi.dump; }
   psql -Atc 'select count(*) from published.document'
   EOF
   )"
   ```
   **Pass:** the last line of the log is `2561`, the count on 2026-10-23, and the exit code is `0`. A warning from `pg_restore` about the owner of schema `public` is harmless. Run it once only: a second run stops at `role "bi" already exists`.
5. **Migrations.** A no-op at migration 15, but it proves the API's settings reach Aurora:
   ```bash
   run_task cli metamorph-sg-api db migrate
   ```
6. **The blobs, from SeaweedFS straight to S3.** Their keys (`blobs/<2>/<sha256>`) are content addresses, so they stay valid:
   ```bash
   AWS_ACCESS_KEY_ID=metamorph AWS_SECRET_ACCESS_KEY=metamorph-dev-secret \
     aws s3 sync s3://metamorph-blobs ~/metamorph-deploy/blobs --endpoint-url http://localhost:8333 --region us-east-1
   aws s3 sync ~/metamorph-deploy/blobs "s3://metamorph-blobs-$ACCOUNT/"
   aws s3 ls "s3://metamorph-blobs-$ACCOUNT/" --recursive --summarize | tail -2   # 13,455 objects, 2.99 GB (2026-10-23)
   ```

## Phase 5: the API and the web app

1. **Start the API:**
   ```bash
   deploy api --parameter-overrides DesiredCount=1
   ```
2. **The certificate.** Request it, add its validation record to your DNS, and wait:
   ```bash
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

## Phase 6: check, then go live

**Go when every line passes:**

| Check | How |
|---|---|
| The app works over HTTPS | Sign in at `https://$DOMAIN`. Open a document, read a text, open its PDF (a signed S3 link), and see the footer "Text extraction by MinerU" |
| The registry came across whole | The overview's counts match the Mac's, noted in Phase 4 |
| Uploads work | **Add Document** with a small PDF: it goes from the browser straight to S3 |
| Curation reaches the published schema | Correct something small, then `run_task cli metamorph-sg-api build` exits `0` and the change shows as published |
| The API isn't public | `aws elbv2 describe-load-balancers --names metamorph-api --query 'LoadBalancers[0].Scheme'` says `internal` |
| Only the public load balancer is open | `aws ec2 describe-security-groups --filters Name=tag:aws:cloudformation:stack-name,Values=metamorph-foundation --query 'SecurityGroups[].IpPermissions[].IpRanges[].CidrIp'` shows `0.0.0.0/0` twice: its ports 80 and 443 |
| Aurora pauses | After 15 minutes with nobody signed in, CloudWatch's `ServerlessDatabaseCapacity` for `metamorph-1` drops to 0. A paused instance still reports `available` |

**Then go live:** tell the curators the new address. The Mac stays a development stack, with its DAGs paused until the ingestion layer takes over.

## Operating it

**Deploying a change.** Commit, push the image that changed under a new tag, and deploy the stack that uses it:

| Changed | Push | Deploy |
|---|---|---|
| The web app | `TAG=… deploy/aws/push-images.sh curation-web` | `deploy web --parameter-overrides WebTag=$TAG` |
| The platform | `TAG=… deploy/aws/push-images.sh platform` | `deploy api --parameter-overrides PlatformTag=$TAG`, then `run_task cli metamorph-sg-api db migrate` if there is a new migration |

`aws cloudformation deploy` keeps a parameter you don't pass as it was. A deployment that fails its health checks rolls back by itself, through the circuit breaker on both services. To return to an older version, deploy the old tag.

**Publishing curators' work** until the ingestion layer does it: `run_task cli metamorph-sg-api build`, then `run_task cli metamorph-sg-api health`. Run them daily, or after a session of corrections.

**Logs:** `aws logs tail /metamorph --follow --log-stream-name-prefix metamorph-api`, or `metamorph-web`, `metamorph-cli`, `metamorph-dbops`.

**Restoring:**

| What is lost | From |
|---|---|
| The database, or a mistaken change | Aurora's point-in-time restore, to any second of the last 7 days, into a new cluster. Put its host in the URL parameters and restart the API |
| The blobs | The bucket keeps every blob, and nothing may delete one. It is kept even if its stack is deleted |
| The settings | Parameter Store keeps each parameter's history: `aws ssm get-parameter-history --name … --with-decryption` |

**Rolling back to the Mac:** its stack and data stay as they were at the cut-over. Dump Aurora to the operations bucket with a `metamorph-dbops` task (`pg_dump`, then `aws s3 cp`), restore the dump on the Mac, and point curators back.

**Taking it down,** in reverse order:
1. Delete the `metamorph-web` and `metamorph-api` stacks.
2. Turn off the cluster's deletion protection, then delete `metamorph-database`. A final snapshot is kept.
3. Empty the two ECR repositories and the operations bucket, then delete `metamorph-foundation`. The blobs bucket is kept on purpose: delete it by hand.

## What can go wrong

| Risk | What happens | What to do |
|---|---|---|
| A resource the role may not tag or create | The stack fails, as EFS did, with `not authorized to perform …` | The message names the action. Ask for it, or drop that property. Delete a stack whose first creation failed before deploying it again |
| The bucket policy is refused | `MalformedPolicy: Invalid principal` | The role's ARN must be exact: `aws iam get-role --role-name Project3EcsTaskExecutionRole --query Role.Arn` |
| A task can't read its settings | It stops with `ResourceInitializationError … ssm` | A parameter it names is missing: the table in [Settings](#settings-in-parameter-store) |
| The API's S3 calls fail | `AccessDenied` on opening a PDF or uploading | `BucketRoleArns` must contain the role the API runs as (`AppRoleArn`) |
| The web app can't reach the API | Pages fail with a connection error | `/metamorph/web/api-url` is written by the API stack: deploy it before the web stack, then restart the web service |
| The first request after a pause is slow | A curator waits about 15 seconds while Aurora wakes | Expected. Set `MinCapacity=0.5` if that matters more than the $50 a month |
| No certificate | `aws acm wait` times out | The validation CNAME must be exactly as ACM gave it |
| A secret leaks | | Secrets exist only in Parameter Store, encrypted, and reach a container at its start. Rotate: `secret … <new value>`, then restart the services that read it |
