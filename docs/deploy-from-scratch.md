# Deploy from scratch in your own AWS account

The full procedure for a new deployment of the platform, retrieval and MIRA, and for rebuilding one after a disaster. Each step depends on the ones before it. The Operational readiness document explains why each step exists; this file has the commands.

The Metamorph-Sharia team runs a working deployment of this design, called the reference. Its values appear below as examples ("reference: …"). Nothing here needs access to it.

The procedure has not yet been run end to end in a fresh account. The reference was built in this order by hand, and `deploy/aws/lib.sh` and `deploy/collection-host/setup.sh` wrap those same commands without having been run as scripts.

## Contents

- [Before you start](#before-you-start)
- [Step 0: forks and the reference's values](#step-0-forks-and-the-references-values)
- [Steps 1 to 14](#steps-1-to-14)
- [Your domain](#your-domain)
- [The collection host](#the-collection-host)
- [Step 11: the MIRA API by hand](#step-11-the-mira-api-by-hand)
- [Step 14: the first load](#step-14-the-first-load)

## Before you start

- The AWS CLI v2, signed in to your account with a deployer role (`aws sts get-caller-identity`), Docker with buildx, uv and Python 3.13.
- Everything listed in the Technical handover, section 2.4: forks of the repositories, the IAM roles from `deploy/aws/iam/`, Bedrock model access, a GPU quota of at least 8 vCPUs for G instances, a domain, an Apple Developer team and a collection host.
- Commit and push to your forks before building: every image tag must name code that is in git.

Every command below runs from this repository with the helpers loaded:

```bash
cd Metamorph-Knowledge-Platform
export AWS_REGION=<region>                      # reference: ap-southeast-3
export METAMORPH_EXECUTION_ROLE=<role name>     # your ECS task execution role
export METAMORPH_OWNER_TAG=<owner>              # optional
DOMAIN=<domain>                                 # api.$DOMAIN and curation.$DOMAIN
source deploy/aws/lib.sh                        # ACCOUNT, ROLE, deploy, setting, secret, exported, run_task
```

`deploy/aws/lib.sh` explains each helper in its header.

## Step 0: forks and the reference's values

Fork every repository at the reference tag. A few values from the reference are written into the code rather than passed as parameters. Replace them in your forks and commit:

| Where | Reference value | Replace with |
|---|---|---|
| This repository, `deploy/aws/iam/*.json` | The reference's account ID and its execution role name | Your account ID and your task execution role |
| mira-ai-chatbot, `deploy/aws/*.json` (restore drill, task trust and secret policies) | Account ID, region, execution role | Yours |
| `deploy/aws/ingestion/*.yaml`, `deploy/aws/ingestion/waf.sh`, `deploy/aws/dev/waf.sh`, mira-ai-chatbot `deploy/langfuse/aws/langfuse-aws.sh` | The tag `Owner=project3`, which the reference's organisation requires | Your own tag, or none |
| `deploy/aws/push-images.sh` (default only), `deploy/aws/ingestion/check.sh`, `deploy/aws/ingestion/mineru.yaml`, mira-ai-chatbot `deploy/aws/mira-api-alarms.sh` and `deploy/langfuse/aws/langfuse-aws.sh` | Region `ap-southeast-3` | Your region |
| mira-ios and mira-macos, `project.yml` | Bundle IDs `my.id.mira-ai.*` and the reference's Apple team | Your bundle IDs and team |
| mira-ios, `Packages/MiraKit/Sources/MiraData/Session/ServerSettings.swift` | The default API address | `https://api.<domain>` |

The reference built MinerU's image with a CodeBuild project it created by hand (`metamorph-mineru-image`; see `deploy/aws/ingestion/README.md`, step 5). Create an equivalent project whose role may push to ECR, or build the image with `docker buildx build --platform linux/amd64 … --push docker/mineru`.

## Steps 1 to 14

| # | Step | Command or action | Done when |
|---|---|---|---|
| 1 | Foundation: cluster, buckets, ECR, security groups | `deploy foundation --parameter-overrides VpcId=… Subnets=… PrivateZones=… ExecutionRoleArn="$ROLE" AppRoleArn="$ROLE" BucketRoleArns="$ROLE" AppOrigin="https://curation.$DOMAIN"` | Stack complete |
| 2 | Secrets | `secret /metamorph/database/master-password …`, then `/metamorph/api/web-secret` (`openssl rand -hex 32`), `/metamorph/api/curators` (`uv run metamorph curator hash-password`), `/metamorph/api/clients` (`uv run metamorph client token mira`) | Parameters exist |
| 3 | Database (RDS PostgreSQL 16) | `deploy database`, then write `/metamorph/platform/database-url` from `setting /metamorph/database/host` | Instance available |
| 4 | Images | `TAG=$(date -u +%Y%m%d-%H%M)`, then `TAG=$TAG deploy/aws/push-images.sh` | "pushed with tag …" |
| 5 | Platform API | `deploy api --parameter-overrides PlatformTag=$TAG DesiredCount=0`, `run_task cli metamorph-sg-api db migrate`, then `deploy api --parameter-overrides DesiredCount=1` | Target healthy on `/healthz` |
| 6 | Certificates | In ACM in **us-east-1** (CloudFront takes certificates only from there), request `curation.$DOMAIN` and `api.$DOMAIN` with DNS validation. See [Your domain](#your-domain) | Certificates issued |
| 7 | Curation Web | `deploy web --parameter-overrides WebTag=$TAG DomainName="curation.$DOMAIN" CertificateArn="$CERT"`, then the `curation` CNAME | Sign-in works over HTTPS |
| 8 | Retrieval | Metamorph-Retrieval `docs/deploying.md`, checklist steps 1 to 3 and 6: push the `retrieval` image, grant the schemas with `metamorph-dbops`, `deploy retrieval --parameter-overrides RetrievalTag=$TAG GatewayCount=0`, then `GatewayCount=1`. The indexes are built after the first load (step 14) | Gateway `/health` ok |
| 9 | Processing and MinerU on AWS | `deploy/aws/ingestion/README.md`, "The deployment order, on AWS": the stacks `ingestion/shared`, `ingestion/jobs`, `ingestion/mineru` (with its front door and WAF), `ingestion/airflow` and `ingestion/alerts`, with the roles from `deploy/aws/iam/`; then unpause the processing DAGs | `deploy/aws/ingestion/check.sh` passes |
| 10 | Collection host | [The collection host](#the-collection-host) | A hand run uploads a bundle and AWS loads it |
| 11 | MIRA API, by hand | [Step 11](#step-11-the-mira-api-by-hand) | `GET https://api.$DOMAIN/v1/meta` answers |
| 12 | Langfuse (optional) | mira-ai-chatbot `deploy/langfuse/aws/langfuse-aws.sh deploy`, then `check`; put its keys in the MIRA secret | A test trace reads back |
| 13 | Budget alerts | `aws budgets create-budget` with email alerts at 50%, 80% and 100% | Budget listed |
| 14 | First load and baseline | [Step 14](#step-14-the-first-load) | Every eval at least matches the reference baseline |

`docs/aws-deployment-guide.md` records how the reference itself was deployed, including moving its data off a Mac. It is history, not part of this procedure: a new deployment starts empty and fills itself in step 14.

## Your domain

Only two names need your domain: `api.<domain>` for the apps and `curation.<domain>` for curators. Airflow, MinerU's front door and Langfuse can stay on their `*.cloudfront.net` addresses. At your DNS provider:

1. Request each certificate in ACM in us-east-1 with DNS validation, and add the CNAME records ACM shows. Leave them in place for good: ACM renews a certificate only while its records exist.
2. Once each distribution exists, add a CNAME from `curation` (step 7) and from `api` (step 11) to the distribution's `*.cloudfront.net` name. On a bare apex domain, use your provider's ALIAS or ANAME record instead.
3. Check with `dig +short api.<domain>` and an HTTPS request to `https://api.<domain>/v1/meta`.

## The collection host

The host must reach the sources from an Indonesian internet line that is not a cloud, data-centre or VPN address ([ADR 0001](adr/0001-collection-on-a-residential-host.md)). The reference uses an Apple Silicon Mac with Docker Desktop, signed in with an AWS SSO session, and only macOS has been tested. An always-on machine is a better choice, with an IAM identity that may only write `bundles/` in the blobs bucket and `backups/` in the ops bucket. The reference has not tried that setup.

On the host, clone this repository and every connector into one folder, then:

```bash
cp .env.example .env                       # METAMORPH_WORKSPACE, the buckets, MinerU's front door and key, the AWS profile
aws sso login --profile <profile>          # or the host's own credentials
deploy/collection-host/setup.sh            # checks the settings and sign-in, builds the images, starts Airflow on :8080
```

`.env.example` explains each setting. Compose runs this Airflow as the collection side (`METAMORPH_SIDE=collection`). `setup.sh --check` runs only the checks.

Every DAG starts paused. Unpause an `ingest_*` DAG to enable its source. Before relying on the schedule, make one hand run per connector inside MinerU's window: its `upload` task finishes on the host, then the connector's task in AWS's `load_bundles` succeeds within 30 minutes. If a source refuses the host (a 403, a challenge page or dropped connections), the address is wrong for this job. Never vary headers or addresses to get around a refusal.

Operating the host (signing in again, held bundles, MinerU's window, rollback) is in `deploy/aws/ingestion/README.md`.

## Step 11: the MIRA API by hand

The MIRA API has no template. mira-ai-chatbot `docs/DEPLOYING.md`, "What runs", lists the reference's resources, and "Accounts" its Sign in with Apple settings. Create the same in your account:

1. An ECR repository (reference: `mira-chatbot`). Database `mira` and role `mira_service` on the RDS instance, with an inbound rule from the service's security group to the database's. That rule is not in a template.
2. A Secrets Manager secret (reference: `mira/chatbot-demo/runtime`) with `MIRA_DATABASE_URL`, `METAMORPH_PLATFORM_TOKEN`, the six `MIRA_APPLE_*` settings from your Sign in with Apple key, and `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` if you run Langfuse.
3. Task definitions `mira-api` (containers `chatbot` on port 8002 and `jobs`, one x86-64 image) and `mira-admin` (the same image, container `admin`, for one-off commands), with a log group. Point `METAMORPH_RETRIEVAL_GATEWAY_URL` at the gateway's private address, and set `MIRA_SUPPORT_EMAIL=help@<domain>`.
4. Target group `mira-api-tg` with health check `/readyz`, and an ALB listener rule that sends requests with the header `X-Mira-Service: api` to it.
5. ECS service `mira-api` on cluster `metamorph`, with the deployment circuit breaker on.
6. A CloudFront distribution in front of the ALB that adds the header, with the `api.<domain>` certificate, and the `api` CNAME at your DNS provider.
7. The first image and the migrations: `deploy/aws/release.sh --migrate` in mira-ai-chatbot (see "Release" in `docs/DEPLOYING.md`).
8. The alarms: `deploy/aws/mira-api-alarms.sh`. Subscribe an on-call address to its topic, `mira-api-alerts`; a topic with no subscriber tells no one.

## Step 14: the first load

A new deployment starts with an empty corpus.

1. On the collection host, inside MinerU's window, run each `ingest_*` DAG once by hand: the regulation connectors first (`ingest_ojk`, `ingest_bpk`, `ingest_bi`, `ingest_dsn_fatwa_full`), then the register, statistics and reports connectors. `ingest_bps_stats` stays paused until its connector is fixed for BPS's new pages.
2. Each run uploads a bundle, `load_bundles` loads it, and registry build and publish follow. Scanned documents make the first runs much longer than later ones. If a run outlasts the window, start the GPU by hand (`deploy/aws/ingestion/README.md`, "The window").
3. Build the regulation and market indexes (Metamorph-Retrieval `docs/deploying.md`, step 4, and `scripts/refresh-market-index.sh`).
4. Run the eval sets and compare them with the reference baseline in the Operational readiness document, section 3.3.
5. Unpause the scheduled DAGs.

The reference's curators' corrections are not carried over. Their overrides live in the reference's database, so your curators work through the held and gap queues again. A seed from the reference's data can be arranged separately; it is not part of this procedure.
