# Deploying Metamorph on AWS: the revised plan

**Date:** 2026-10-30 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Status:** the core on RDS and the retrieval stack are deployed (2026-10-30, [§3](#3-where-we-are)); ingestion waits for permissions ([§7.0](#70-what-the-account-allows-on-2026-10-30-and-what-is-still-missing)) · **For:** whoever deploys and runs Metamorph on AWS, and whoever approves its permissions

**Supersedes** the architecture in [aws-deployment-guide.md](aws-deployment-guide.md) (the core, deployed 2026-10-23) and [deploy/aws/ingestion/README.md](../deploy/aws/ingestion/README.md) (designed, never deployed). Both were shaped by the `Project3Learner` role's limits. Those limits are being lifted, so this plan revisits every choice they forced. The guide stays the record of what is running today, until Phase 4 below replaces it.

It covers three things:
- the **ingestion layer**, for regulations and market data;
- the **platform pieces not yet on AWS**;
- **Metamorph Retrieval** for market data.

## Contents

1. [Summary](#1-summary)
2. [What we design for](#2-what-we-design-for)
3. [Where we are](#3-where-we-are)
4. [Review of the earlier plan](#4-review-of-the-earlier-plan)
5. [The target architecture](#5-the-target-architecture)
6. [What it costs](#6-what-it-costs)
7. [Permissions to request](#7-permissions-to-request)
8. [The implementation plan](#8-the-implementation-plan)
9. [Code and template changes](#9-code-and-template-changes)
10. [Risks](#10-risks)
11. [Decisions for the owner](#11-decisions-for-the-owner)

## 1. Summary

**The shape stays:**
- one ECS cluster on Fargate Graviton;
- one PostgreSQL;
- S3 for blobs;
- Parameter Store for settings;
- Airflow only schedules, and each task is its own container;
- CloudFormation, one stack per piece.

What changes is what the account's limits forced, and what the system has grown since 2026-10-23.

| Area | Deployed or designed before | Now | Why |
|---|---|---|---|
| Database | Aurora Serverless v2, pausing at 0 ACU | **RDS for PostgreSQL 16, `db.t4g.medium`, Single-AZ, gp3** | The SCP allowed only Aurora. Once ingestion, Airflow and retrieval run, nothing lets Aurora pause. The same 4 GiB of memory then costs about 2.9× as much ([§4.1](#41-aurora)) |
| Network | The default VPC; public subnets with a public IP per task; no NAT | **A VPC of our own: private subnets for every task, one NAT gateway, an S3 gateway endpoint** | Nothing faces the internet but CloudFront. The connectors reach the sources from **one stable IP address**, not a rotating pool ([§5.2](#52-network)) |
| Load balancing | Two internal ALBs: web and API | **One internal ALB, one listener per service** (web, API, retrieval) | Saves about $19 a month. Each service's stack still owns its own listener |
| IAM | One shared execution role, which is also the app role | **A role per task family,** each under one permissions boundary | Least privilege. The boundary lets the stacks create roles without the deployer holding wide IAM rights |
| Ingestion | 4 regulation connectors (designed) | **9 connectors:** the 4 regulation connectors, plus OJK register, OJK stats, BI SEKI, BPS and Reports | The market data layer, built since |
| MinerU | A GPU window, 00:30–03:15 UTC | **The same design, with its window matched to the DAGs.** `ingest_reports` (Mondays 04:45) falls outside today's window | A Reports run with a new PDF would fail |
| Retrieval | Not planned | **The gateway as an ECS service behind the internal ALB, plus the index refresh as a task Airflow runs.** bge-m3 is baked into the image | Built in M3 and M4 since |
| Observability | Logs, plus a budget | **Logs, alarms, an ECS task-failure rule, retrieval latency metrics, a dashboard, Cost Anomaly Detection** | Production-ready means a failure reaches someone |
| Delivery | `push-images.sh` from the Mac, tagged by time | **The same script, tagged by git commit;** GitHub Actions with OIDC later | An image always names its code |
| IaC | CloudFormation | **CloudFormation, deployed through a CloudFormation service role** | The failures were missing permissions, not CloudFormation ([§4.2](#42-cloudformation)) |

**Monthly cost, Jakarta on-demand:** about **$320–425**, depending on two choices:
- the gateway's hours;
- the MinerU window.

The old plan's sum was $316. That figure left out retrieval, and assumed Aurora would sit at 0.5 ACU. [§6](#6-what-it-costs) has the breakdown.

## 2. What we design for

These are the inputs the AWS solution-architect method starts from. Our answers:

| Input | Our answer | What follows |
|---|---|---|
| **Users** | A handful of curators, in working hours. Friend 1's agent evaluation, then an answering agent | Small and steady. No autoscaling beyond 1–2 tasks. Scheduled scale-to-zero is worth it |
| **Traffic** | The curation app: tens of requests a minute at peak. Retrieval: an agent's tool calls, p95 174 ms locally | One small task per service. Retrieval latency is the number to watch |
| **Data** | PostgreSQL 5.5 GB:<br>- `published_market` 2.1 GB<br>- `published` 2.0 GB<br>- `market` 0.6 GB<br>- `registry` 0.5 GB<br>- `retrieval_market` 0.3 GB<br>Connector state about 8 GB, including the MinerU caches (190 MB, costly to rebuild). Blobs about 3.5 GB | A small database. Its working set nearly fits in 4 GiB. File state needs a shared file system |
| **Workload shape** | Ingestion is nightly and weekly: about 70–120 task-minutes a day, plus a registry build of up to 2 hours. A GPU only while PDFs are read | Batch on Fargate. The GPU only in a window |
| **Budget** | Hundreds of dollars a month, not thousands. The SCPs used to force Aurora's pause, which only saves money while nothing connects | Fixed-size, cheap, predictable pieces, with no pay-per-use surprises |
| **Team** | One owner deploys. Two friends consume. Little ops time | Managed services, few moving parts, runbooks over automation where both work |
| **Compliance** | Indonesian public legal and market data, published. No personal data beyond curators' accounts | Jakarta region. Encryption at rest and in transit. No special regime |
| **Availability** | An internal tool and an evaluation API. Hours of downtime are tolerable; data loss is not | **RPO 5 minutes** (the database, by point-in-time restore) and **24 hours** (file state). **RTO about 2 hours.** Single-AZ now; Multi-AZ when retrieval serves end users |

## 3. Where we are

### Deployed on 2026-10-30, within the account's current permissions ([§7.0](#70-what-the-account-allows-on-2026-10-30-and-what-is-still-missing))

**Still the default VPC and its public subnets:** the role may not create a NAT or internet gateway.

| Step | What was done | Check |
|---|---|---|
| Aurora's last state | Dumped to `s3://metamorph-ops-<account>/exports/aurora-final-2026-10-30.dump` and `aurora-bi-2026-10-30.dump` (kept 30 days). Since the cut-over it held one curator action: a text correction of `bi:pbi:2004:25` (Pasal 19 merged into Chapter III's heading), made against the same text the Mac still publishes | |
| RDS for PostgreSQL | `metamorph-pg`: 16.15, `db.t4g.medium`, gp3 50 GB growing to 200, 14 days of backups, deletion protection, `rds.force_ssl`. In stack `metamorph-database`, beside the Aurora cluster, which stays until the owner confirms its removal. `/metamorph/database/host` and the platform's database URL now name RDS | |
| The Mac's database | Restored into RDS. The text correction and its audit entry were replayed. `metamorph build` republished that one document. A role `retrieval_reader` (read-only, `published`, `published_market`, `retrieval_market`) was created | Migration 22. Equal to the Mac on:<br>- 2,561 documents<br>- 261,320 provision units<br>- 68 overrides<br>- 1,919 review items<br>- 15 `published_market` tables<br>- the active index, `market-2026-10-30.6`, 7,022 units<br>pgvector 0.8.2 |
| Blobs | Synced from the Mac's SeaweedFS into the kept bucket | 25,622 objects, 3.69 GB |
| API and web | `metamorph/platform:1fb3c45`, `metamorph/curation-web:511a34a`, one task each | Both targets healthy. `https://curation.mira-ai.my.id/sign-in` answers 200 |
| Retrieval | Stack `metamorph-retrieval`: the repository, `metamorph/retrieval:724c16d`, the `metamorph-retrieval` refresh task, and the `retrieval-gateway` service at 0 tasks (nothing outside the VPC can reach it yet) | Through the gateway in a task on AWS: **52/54, R 0.89, MRR 0.82**, the same as the Mac. `search_documents`: p50 445 ms, p95 701 ms on 2 vCPU Graviton, over the 500 ms target. The account caps tasks at 2 vCPU |
| Health | `metamorph health` | `critical`: OJK, BPK and BI last loaded 184 hours ago. Expected while no ingestion runs anywhere |

**Not deployed:**
- **Ingestion and MinerU.** They need EFS, a role that may run ECS tasks, Auto Scaling and a GPU instance, all missing ([§7.0](#70-what-the-account-allows-on-2026-10-30-and-what-is-still-missing)).
- **The private VPC.** It needs NAT and internet gateway permissions.
- **Observability.** The alarms and dashboard come in Phase 7.

**Found on AWS:**
- **bge-m3's download from Hugging Face** took 47 seconds once and about 9 minutes the next time. Baking the model into the image ([§9](#9-code-and-template-changes)) is needed for reliable starts, not only reproducibility.

### On AWS since 2026-10-23, per the deployment guide

| Stack | What it runs |
|---|---|
| `metamorph-foundation` | Default VPC, cluster, buckets, ECR (`metamorph/platform`, `metamorph/curation-web`) |
| `metamorph-database` | Aurora Serverless v2 at migration 15, with 2,561 published documents |
| `metamorph-api` | The API, behind its own internal ALB |
| `metamorph-web` | The web app, behind its own internal ALB, served by CloudFront through a VPC origin |

No connector runs on AWS. Curators' changes are published by a hand-run `metamorph build`.

**On the Mac since then.** Everything below is committed and pushed in all twelve repositories (checked 2026-10-30):

| Change | Effect on AWS |
|---|---|
| Migrations 16–22: the market layer (`market`, `published_market`), market curation | The AWS database is 7 migrations behind |
| The MinerU rollout, live (steps 1–13) | The Mac's texts differ from AWS's for re-read documents |
| Five market connectors, each with its own image | Not in any template |
| The `market_publish` and `market_index` DAGs | Not in any template |
| Metamorph Retrieval: the gateway, the market index (`retrieval_market`, pgvector) and bge-m3 | Needs pgvector, which Aurora has, and a 3.4 GB image |
| The curation web app's market pages | The deployed web image predates them |
| The 68 citation overrides | Exist on the Mac only |

**Not verified for this plan:**
- **The live AWS state.** The SSO session had expired on 2026-10-30, so the stacks, Aurora's state and whether curators changed anything on AWS since 2026-10-23 are taken from the guide. Phase 0 checks them.

## 4. Review of the earlier plan

### 4.1 Aurora

**Aurora was imposed, not chosen.** The organization's SCP had two rules:
- `AuroraEnginesOnly` denied the `postgres` engine;
- `AuroraServerlessV2Only` denied any instance class but `db.serverless`.

The guide made the best of it: pause at 0 ACU, $21 a month while curators sleep. That only holds for a database that nobody connects to.

| Issue | Detail |
|---|---|
| **It stops pausing once the system is whole** | Airflow's scheduler holds connections around the clock, and so do the retrieval gateway and the API's pool. Aurora then never reaches 0 ACU. The ingestion README already counted this |
| **0.5 ACU is about 1 GiB of memory** | Too little for a 5.5 GB database, a 2-hour registry build and hybrid search. In practice it would sit at 1–2 ACUs and climb during builds. 2 ACU = $292 a month; the same memory on RDS (`db.t4g.medium`, 4 GiB) costs $74 |
| **Waking takes about 15 seconds** | The retrieval provider's statement timeout is 8 s, and the gateway's per-call timeout 10 s. The first agent call after a pause would fail as `provider_unavailable`. Curators wait too |
| **I/O is billed** | $0.22 per million I/Os on Aurora Standard, or 30% more per ACU on I/O-Optimized. Builds and index refreshes are I/O-heavy |
| **What Aurora would add, we don't use** | Read replicas, Global Database, storage growing past what a 50 GB volume holds, sub-minute failover. None is a need at 6 GB with one writer |

**Recommendation: RDS for PostgreSQL 16, `db.t4g.medium`, Single-AZ, 50 GB gp3** with storage autoscaling to 200 GB. That is $74.46 a month for the instance, and $6.90 for the storage.

| Option | Monthly | Verdict |
|---|---:|---|
| **RDS `db.t4g.medium`** (2 vCPU burstable, 4 GiB), Single-AZ | $74 + storage | **Chosen.** PostgreSQL 16 as on the Mac, pgvector included. Fixed cost |
| RDS `db.t4g.large` (8 GiB) | $148 | The first step up, if `FreeableMemory` stays under 500 MB |
| RDS `db.m7g.large` (8 GiB, not burstable) | $172 | If builds use up the CPU credits every night |
| RDS Multi-AZ (`db.t4g.medium`) | $148 + double storage | When retrieval serves end users with an availability target |
| Aurora Serverless v2, a 1–2 ACU floor | $146–292 + I/O | Rejected: it costs more for the same memory, and the pause no longer happens |

**Revisit Aurora** if any one of these becomes true:
- the database needs read replicas for retrieval at scale;
- it needs a failover under a minute;
- it grows past a few hundred GB.

**On RDS, keep:**
- automated backups for 14 days, which give point-in-time restore;
- deletion protection;
- encryption with the `aws/rds` key;
- `rds.force_ssl=1`;
- the master password managed by RDS in Secrets Manager (`ManageMasterUserPassword`), with rotation;
- one login role per consumer ([§5.6](#56-security-and-iam));
- Database Insights, standard mode, which is free;
- `log_min_duration_statement=1000`.

### 4.2 CloudFormation

Each failure on 2026-10-23 was a **permission, not CloudFormation:**
- `elasticfilesystem:TagResource` was denied;
- ACM in Jakarta was denied by the SCP;
- the RDS engine was denied by the SCP.

What did come from the tooling was a deploy that sat silent while it waited:
- `aws acm wait` ran into `deploy web` in one paste;
- the terminal looked stuck.

**Keep CloudFormation.** The reasons:
- The templates exist, pass `cfn-lint` and `validate-template`, and their layering is tested (`tests/test_deploy_layers.py`).
- CDK would bring a new toolchain and a rewrite, with no capability we need.
- Terraform would add state to manage.

**Change how it is used:**
1. **A CloudFormation service role,** `metamorph-cfn-exec`. It holds the permissions to create resources; the deployer needs only `cloudformation:*` on `metamorph-*` stacks and `iam:PassRole` on that role. This is what makes approval easy: one reviewed role, not a person with wide rights ([§7](#7-permissions-to-request)).
2. **A permissions boundary on every role a stack creates.** Then a stack can create roles without being able to escalate.
3. **Change sets, reviewed:** `deploy … --no-execute-changeset`, read the change set, then execute it.
4. **One step per command,** never pasted together. Every wait is followed by `describe-stack-events` on failure.
5. **`Fn::ForEach`** (the `AWS::LanguageExtensions` transform) for the nine connectors' task definitions and access points, instead of nine copies.
6. **Termination protection** on the network, database and foundation stacks.

### 4.3 Other findings

| # | Finding | Severity | In this plan |
|---|---|---|---|
| 1 | **Rotating public IPs would show the sources many addresses.** Each Fargate task in a public subnet gets an address from AWS's pool. To OJK, BI, BPS and BPK, a weekly crawl would come from changing addresses. That looks like the evasion our rules forbid, and it makes us untraceable to a site that wants to contact us | High | One NAT gateway: one Elastic IP for all egress. Record it in each connector's README |
| 2 | **`ingest_reports` runs outside MinerU's window** (Mondays 04:45; the window closes at 03:15). Reports reads PDFs through MinerU, so a new PDF fails the task | High | Move it into the window ([§5.4](#54-the-ingestion-layer)) |
| 3 | **The SEKI inbox is a folder in the connector's `data/`.** On AWS that is EFS, which curators can't reach | Medium | An S3 inbox prefix, copied into EFS at task start ([§5.4](#54-the-ingestion-layer)) |
| 4 | **The gateway reads the active index version once, at start, over one connection with no reconnect.** After a weekly refresh activates a new version, a running gateway keeps serving the old one. After an RDS maintenance restart, it fails until replaced | High for retrieval | Re-resolve the active version on a short TTL, reconnect on a lost connection, and make `/health` check the database ([§9](#9-code-and-template-changes)) |
| 5 | **The gateway's call log and the refresh's reports are files under `var/`.** On Fargate they vanish with the task | Medium | The call log as JSON lines on stdout, into CloudWatch Logs, with metrics from them. The refresh prints its comparison to stdout |
| 6 | **bge-m3 is downloaded on first use,** from Hugging Face, into a volume | Medium | Bake a pinned revision into the image: reproducible, rollback exact, no runtime download |
| 7 | **The gateway has no authentication** | Medium | It stays private. People reach it through SSM port forwarding. Add a bearer token before anything outside the VPC calls it |
| 8 | **One role is both execution and app role** | Medium | A role per task family ([§5.6](#56-security-and-iam)) |
| 9 | **Image tags are timestamps** | Low | Tag by git commit (`git rev-parse --short HEAD`), with immutable tags in ECR |
| 10 | **The BPS DAG would resume the backfill** when unpaused | Note | It stays paused until the owner decides |

## 5. The target architecture

### 5.1 The picture

```
 Curators ─HTTPS─► CloudFront (us-east-1 cert) ─VPC origin─┐
                                                           ▼
 ┌─ VPC 10.40.0.0/16, two AZs ──────────────────────────────────────────────────────────────────────────┐
 │  public subnets: NAT gateway + Elastic IP (the one egress address) ──► OJK, BPK, BI, DSN-MUI, BPS…    │
 │                                                                                                      │
 │  private app subnets                                                                                 │
 │   internal ALB ─ :80   ─► web       (Fargate ARM, ECS service)                                       │
 │                ─ :8080 ─► api       (Fargate ARM, ECS service) ◄── web only                          │
 │                ─ :8765 ─► retrieval gateway (Fargate ARM, MCP + HTTP) ◄── agents in the VPC; SSM     │
 │                                                                                                      │
 │   airflow (ECS service, LocalExecutor) ─ ecs:RunTask ─► tasks on Fargate ARM:                        │
 │      9 connectors ──EFS: data/, bundles/──► platform: load → build | market publish                  │
 │                                             └─► retrieval refresh: build index → eval gate → activate│
 │      connectors that read PDFs ──HTTP──► MinerU (g5.xlarge, ECS on EC2, only in its window)          │
 │                                           mineru.metamorph.internal (Cloud Map)                      │
 │                                                                                                      │
 │  private DB subnets: RDS PostgreSQL 16 + pgvector                                                    │
 │     databases: metamorph (ingest, registry, curation, published, market, published_market,           │
 │                retrieval_market) · airflow · bi                                                      │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────┘
 S3 (gateway endpoint): blobs (kept, versioned, no deletes) · ops (transfer, exports, SEKI inbox)
 EFS: one access point per connector + bundles · ECR · Parameter Store /metamorph/prod/* · CloudWatch · AWS Backup
```

| Piece | Runs as | Size | Hours |
|---|---|---|---|
| Web | ECS service | 0.25 vCPU, 0.5 GB | always, or working hours |
| API | ECS service | 0.25 vCPU, 1 GB | always, or working hours |
| Retrieval gateway | ECS service | 2 vCPU, 6 GB, 1 task | working hours at first ([§11](#11-decisions-for-the-owner)) |
| Airflow | ECS service | 0.5 vCPU, 3 GB | always |
| Connectors, platform jobs, retrieval refresh | ECS tasks started by Airflow | per task definition, 0.5–2 vCPU | minutes a day |
| MinerU | ECS service on a g5.xlarge capacity provider | 4 vCPU, 16 GiB, A10G 24 GB | its window |
| One-off commands | `metamorph-cli`, `metamorph-dbops` task definitions | | when run |

### 5.2 Network

- **A new VPC,** `10.40.0.0/16`, over two Availability Zones. Each zone has three subnets:
  - **public:** only the NAT gateway;
  - **private app:** every task, the ALB, EFS mount targets, MinerU;
  - **private DB:** RDS. No route to the internet, and its route table has none.
- **One NAT gateway** in one zone ($43 a month plus $0.059 per GB). If that zone fails, ingestion pauses; the web, API and retrieval keep working, since they need no egress. A second NAT is not worth $43 for that.
- **An S3 gateway endpoint** (free). ECR's image layers come from S3, so image pulls mostly bypass the NAT.
- **No interface endpoints** at first. At $9.50 a month each per zone, the five that would matter (ECR ×2, Logs, SSM, SSM messages) cost more than the NAT data they save.
- **Security groups by role:**
  - ALB: `:80` from CloudFront's prefix list; `:8080` from the web; `:8765` from the agent group;
  - RDS: `:5432` from the API, the jobs, Airflow and retrieval;
  - EFS: `:2049` from the jobs;
  - MinerU: `:8010` from the jobs.
- **VPC Flow Logs,** rejected traffic only, kept 14 days.

**Why a new VPC, not the default one:**
- the default VPC has only public subnets;
- moving to RDS already means a new database endpoint and a data migration;
- doing both together is one cut-over, not two.

### 5.3 The core: web, API, database

- **The web app and the API** are unchanged in kind: one Fargate ARM task each, with the circuit breaker and rollback.
- **They move to private subnets** with no public IP, behind the shared ALB.
- **CloudFront and its us-east-1 certificate stay.** Its VPC origin moves to the new ALB.
- **Scheduled scaling** (Application Auto Scaling) can set the web, API and gateway to 0 at night and 1 in the morning. On RDS it saves only the Fargate hours, about $10 a month for web and API.
- **The database:** as in [§4.1](#41-aurora). It holds three databases:
  - `metamorph`, the platform's;
  - `airflow`;
  - `bi`, the BI connector's own.

**Login roles,** each with only what it needs:

| Role | Rights | Used by |
|---|---|---|
| `metamorph` | Owner of the platform schemas | API, platform jobs, migrations |
| `airflow` | Owner of `airflow` | Airflow |
| `bi` | Owner of `bi` | The BI connector |
| `retrieval_reader` | `SELECT` on `published`, `published_market`, `retrieval_market`; `default_transaction_read_only=on` | The gateway |
| `retrieval_indexer` | Owner of `retrieval_market`; `SELECT` on `published_market` | The refresh |

The `vector` extension is created once, by the master user.

### 5.4 The ingestion layer

**Orchestration: Airflow 2.10 as an ECS service, as designed.**
- It already runs every task through `EcsRunTaskOperator` when `METAMORPH_TASK_LAUNCHER=ecs`. The DAGs and `jobs.py` don't change.
- LocalExecutor, with its metadata in RDS's `airflow` database.

The alternatives, and why not:

| Alternative | Why not |
|---|---|
| **MWAA** | Its smallest environment is $0.29 an hour in Jakarta: $212 a month, against $24 for Airflow on Fargate. It brings nothing Airflow-only-schedules needs |
| **EventBridge Scheduler + Step Functions** | Serverless, and it would cost almost nothing. But it rewrites tested orchestration: the Dataset-driven chain regulation → build and market → publish → index. It also loses the UI where runs are inspected and re-run. Revisit only if Airflow becomes a burden |

**The flow on AWS:**

```
 cron (UTC, jobs.py)
   → collect:  connector task. EFS data/ (SQLite store, PDFs, mineru-cache/); MinerU if a PDF needs reading;
               export a bundle to EFS /bundles
   → load:     platform task: `metamorph load` (regulation) or `metamorph market load` (market)
   → discard
   → Dataset REGISTRY         → registry_build: `metamorph build` → health      → published
   → Dataset MARKET_REGISTRY  → market_publish                                  → published_market
                              → market_index:   refresh-market-index.sh         → retrieval_market
 06:00 UTC daily: health (fails on critical)
```

**Compute.** Each connector has its own task definition, family `metamorph-<image name>` (`jobs.task_family`). Sizes, measured locally and adjusted from CloudWatch after two weeks:

| Task | Size |
|---|---|
| Connectors | 0.5–1 vCPU, 2 GB |
| Platform `build` | 1 vCPU, 4 GB |
| Retrieval refresh | 2 vCPU, 8 GB |

**Storage:**
- **EFS** with one access point per connector (nine), one for `/bundles`, and one for OJK's credentials, if the JDIH source still reads them (Phase 0 checks).
- Elastic throughput, and lifecycle to Infrequent Access after 30 days: the PDFs are mostly cold.
- AWS Backup, daily, kept 35 days. **The MinerU caches are the one costly thing to rebuild.**
- SQLite on EFS is safe here because each DAG runs one at a time (`max_active_runs=1`). One writer per store.

**The SEKI inbox:**
- Curators drop a SEKI zip into `s3://metamorph-ops-<account>/inbox/bi-seki/`.
- The `bi-stats` task definition has a non-essential first container (`amazon/aws-cli`). It copies the prefix into the connector's `data/inbox/` on EFS, then the main container starts (`dependsOn: SUCCESS`).
- No connector code changes. A curation-web upload page can replace the CLI drop later.

**MinerU,** as designed in `mineru.yaml`:
- a g5.xlarge Auto Scaling group with a warm pool (stopped instances cost only their disk);
- an ECS capacity provider, and the MinerU service on it;
- Cloud Map `mineru.metamorph.internal`;
- scheduled actions that open and close the window.

g5.xlarge is the only G instance in Jakarta's price list ($1.408 an hour). Two changes:

1. **Match the window to the DAGs.** The connectors that read PDFs are OJK, BPK, BI, DSN-MUI, OJK register and Reports. Move `ingest_reports` from 04:45 to inside the window, for example Mondays 02:15, after DSN-MUI's weekly 02:00. Keep a test that checks every MinerU-using DAG's start falls inside the window. The schedules in `jobs.py` and the window's parameters in `mineru.yaml` change together, as the README says.
2. **Tighten the window after measuring.** Today's 2 h 45 min a day (about 85 hours a month, $120) was set before any run on AWS. After two weeks, set it to the longest observed regulation run plus a margin, likely 1.5 hours. That is about 50 hours a month, $70.

On-demand, not Spot, at first: a Spot interruption mid-window would fail tasks and retry them past the window's end. Revisit Spot once the window's real length is known.

**Rollback stays configuration:** `/metamorph/prod/connectors/pdf-engine` = `pymupdf`. But OCR is only through MinerU, so under `pymupdf` a scanned PDF fails with a clear message rather than being read. **Ingestion and MinerU go live together.**

**Monitoring ingestion:**

| Signal | How | Alerts |
|---|---|---|
| A task failed | Airflow's `on_failure` already posts to `METAMORPH_ALERT_WEBHOOK_URL` (Slack-compatible). Set it in Parameter Store | Slack |
| A task failed while Airflow was down or misconfigured | EventBridge rule: `ECS Task State Change`, `STOPPED`, any container exit code ≠ 0, in cluster `metamorph` | SNS → email |
| Airflow is down | CloudWatch alarm: the `airflow` service's running task count < 1 for 10 minutes | SNS |
| Ingestion is stale | The daily `health` DAG fails on critical, which is already built | Slack |
| MinerU isn't serving in its window | Connector tasks fail with `ExtractionUnavailable` and retry | Slack |
| A source refused us | The connector's exit code; our rule is to stop. Review before re-enabling | Slack |

### 5.5 Retrieval for market data

**What runs:**

| Piece | As | Reads | Writes |
|---|---|---|---|
| **Gateway** (`metamorph-gateway serve`, MCP at `/mcp`, HTTP tools) | ECS service `retrieval-gateway`, 1 task, 2 vCPU / 6 GB, behind the ALB's `:8765` | `published_market`, `published`, `retrieval_market`, as `retrieval_reader` | Nothing |
| **Index refresh** (`scripts/refresh-market-index.sh`) | Task definition `metamorph-retrieval`, run by the `market_index` DAG after each `market_publish` | `published_market`, as `retrieval_indexer` | A new `retrieval_market` version. It activates it only if `metamorph-eval compare` finds it no worse |

**The image:**
- `metamorph/retrieval:<commit>`, arm64, with CPU torch;
- **bge-m3 baked in at a pinned revision,** so the image tag names the exact model: about 5.7 GB in all;
- the `metamorph-models` volume is for the Mac only;
- ECR pulls go over the S3 endpoint, so their size costs time (about a minute), not money.

**Integration with ingestion:**
- `market_publish` updates the `PUBLISHED_MARKET` Dataset, which triggers `market_index`.
- The refresh embeds only changed units: the embedding cache is in `retrieval_market.embedding_cache` and comes across with the database.
- The gateway then picks up the new active version within its TTL, once [§9](#9-code-and-template-changes)'s change is in. Until then, the DAG restarts the gateway service after a successful refresh.

**Who reaches it:**

| Caller | Path |
|---|---|
| An agent deployed in the VPC (ECS, or a runtime with a VPC attachment) | `http://<internal ALB>:8765/mcp`, from the agent's security group |
| Friend 1, Friend 2, the owner, from their computers | SSM port forwarding into the gateway task (ECS Exec), e.g. `aws ssm start-session --target ecs:metamorph_<task>_<runtime> --document-name AWS-StartPortForwardingSession --parameters portNumber=8765,localPortNumber=8765`. Then `METAMORPH_RETRIEVAL_GATEWAY_URL=http://localhost:8765` works as on the Mac |
| Anything outside AWS, unattended | Not yet. When needed: a bearer token in the gateway first, then an API Gateway HTTP API with a VPC link and a JWT authorizer, or the agent platform's own gateway. Decide when Friend 1's agent has a home |

**Its gates on AWS:**
- `metamorph-eval` through the gateway from inside the VPC gives **52/54**, the same as on the Mac;
- **p95 under 500 ms** for `search_documents` on Graviton. If it is over, use 4 vCPU before anything else;
- the manifest's `index_version` and `data_as_of` match the database.

**Its monitoring:**
- **The call log on stdout** as JSON, one line per call, with CloudWatch embedded metric format fields.
- That gives metrics without new infrastructure:
  - latency per tool (p50, p95);
  - errors by kind;
  - `no_match` rate;
  - answer bytes.
- **Alarms:**
  - p95 over 1 s for 15 minutes;
  - `provider_unavailable` over 5 in 5 minutes;
  - unhealthy targets on `:8765`.
- **OpenTelemetry spans** are already emitted. Export them to X-Ray with an ADOT collector sidecar only once the agent runs on AWS, when one trace across agent and gateway is worth it.

### 5.6 Security and IAM

**Roles,** each created by its stack under the boundary `metamorph-boundary`:

| Role | Allows |
|---|---|
| `metamorph-exec` | ECR pull, Logs, Parameter Store reads of `/metamorph/prod/*`, KMS decrypt for them |
| `metamorph-api` | S3 on the blobs bucket (read, write, presign; no delete) |
| `metamorph-web` | Nothing |
| `metamorph-platform` | S3 blobs (no delete) |
| `metamorph-connector` | EFS client access through its access points (IAM authorization), S3 read of `inbox/` |
| `metamorph-airflow` | `ecs:RunTask`, `DescribeTasks` and `StopTask` on `metamorph-*` task definitions; `iam:PassRole` on the task roles; Logs read for task logs; `ecs:UpdateService` on `retrieval-gateway` |
| `metamorph-retrieval` | Nothing beyond Logs |
| `metamorph-mineru-instance` | The ECS agent's managed policy |
| `metamorph-dbops` | S3 on the ops bucket |

**Everywhere:**
- encryption at rest (S3 SSE-S3, EFS, RDS, ECR) and TLS-only bucket policies;
- Block Public Access;
- blobs versioned, with deletes denied, as today;
- ECR scan on push, immutable tags, and a lifecycle that keeps the last 10;
- ECS Exec enabled, for tunnels and debugging, with its sessions logged.

**Secrets** stay in Parameter Store SecureString, as the owner chose, under `/metamorph/prod/`. The one exception is the RDS master password, which RDS manages in Secrets Manager ($0.40 a month) with rotation.

**Account level:**
- Check that an organization CloudTrail exists; if not, create one trail to the ops bucket.
- Turn on IAM Access Analyzer (free) and Cost Anomaly Detection (free).
- GuardDuty is optional, a few dollars a month.
- **WAF on CloudFront** is optional: the curation app has its own sign-in, and few users. Add the managed common rule set and a rate rule (about $8 a month) if the address becomes widely known.

### 5.7 Observability

- **Logs:**
  - one log group per service and task family under `/metamorph/prod/`;
  - kept 30 days; the retrieval call log kept 90 days, for evaluation.
- **One CloudWatch dashboard,** `metamorph`:
  - ALB requests and 5xx by listener;
  - ECS CPU and memory per service;
  - RDS CPU, credits, memory, connections and storage;
  - retrieval latency and `no_match` rate;
  - MinerU window state;
  - task failures by family.
- **Alarms** go to one SNS topic, by email, and to Slack through Amazon Q Developer in chat applications or the same webhook:

| Service | Alarms |
|---|---|
| ALB | 5xx > 5 in 5 min; `UnHealthyHostCount` > 0 |
| RDS | CPU > 80% for 15 min; `CPUCreditBalance` < 50; `FreeableMemory` < 300 MB; `FreeStorageSpace` < 10 GB |
| ECS | a service's running tasks below desired for 10 min |
| Retrieval | the alarms in [§5.5](#55-retrieval-for-market-data) |
| Cost | the budget at 50%, 80% and 100%; Cost Anomaly Detection |

- **Not added:**
  - Container Insights enhanced, an extra cost the dashboard covers;
  - a third-party APM;
  - Synthetics canaries. The ALB's health checks and the daily `health` DAG cover liveness.

### 5.8 Backup and recovery

| What | How | RPO | Restore |
|---|---|---|---|
| Database | RDS automated backups, 14 days, plus point-in-time restore. A monthly AWS Backup snapshot, kept 12 months | 5 min | Restore to a new instance, then point `/metamorph/prod/*/database-url` at it and restart the services. About 30–60 min |
| Connector state, MinerU caches | AWS Backup of EFS, daily, kept 35 days | 24 h | Restore files into the access point |
| Blobs | Versioned, deletes denied, kept if the stack is deleted | 0 | Already there |
| Settings | Parameter Store history | 0 | `get-parameter-history` |
| Images | ECR, immutable tags by commit | 0 | Deploy the old tag |
| Everything, if the region is lost | Not covered now. The source repositories, and a weekly `pg_dump` of `published` and `published_market` in the ops bucket, are the floor. A cross-region backup copy (AWS Backup to Singapore) is one setting if it is ever wanted | | |

**Practise each restore once** in Phase 7, before calling the system production.

### 5.9 Infrastructure as code and delivery

**Stacks,** under new names. The old ones keep running until the cut-over, then are deleted.

| Stack | Holds | Replaces |
|---|---|---|
| `metamorph-prod-network` | VPC, subnets, NAT, endpoints, flow logs | the default VPC |
| `metamorph-prod-foundation` | Cluster, shared ALB, security groups, log groups, SNS topic, execution role, boundary. **Adopts** the existing ECR repositories and buckets (resource import) | `metamorph-foundation` |
| `metamorph-prod-database` | RDS, its parameter group, `metamorph-dbops` | `metamorph-database` |
| `metamorph-prod-api`, `metamorph-prod-web` | Each service, its role, its listener and target group | `metamorph-api`, `metamorph-web` |
| `metamorph-prod-ingestion-shared` | EFS and its access points, Cloud Map, ingestion repositories, roles | the designed `metamorph-ingestion-shared` |
| `metamorph-prod-ingestion-jobs` | Task definitions: platform, the nine connectors, ops | the designed `metamorph-ingestion-jobs` |
| `metamorph-prod-ingestion-airflow` | The Airflow service | the designed `metamorph-ingestion-airflow` |
| `metamorph-prod-ingestion-mineru` | The GPU group, capacity provider, MinerU service, window | the designed `metamorph-ingestion-mineru` |
| `metamorph-prod-retrieval` | The gateway service, its listener, the `metamorph-retrieval` refresh task definition, retrieval alarms | new |
| `metamorph-prod-observability` | Dashboard, shared alarms, the ECS failure rule, budget, Backup plan | new |

**Conventions:**
- The `prod` in each name leaves room for a staging copy later. The Mac's compose stack stays the development and staging environment.
- Tags: `Project=metamorph`, `Environment=prod`, `Owner=project3`. They are cost allocation tags too.

**Delivery:**
- **Now:** `push-images.sh`, building arm64 on the Mac and tagging by commit, then `deploy <stack>` with the new tag.
- **Later:** a GitHub Actions workflow per repository, with an OIDC role (`metamorph-github-deploy`) that may push to its own ECR repository only, building on arm64 runners. Deploys stay manual until there is a staging copy to test on.

## 6. What it costs

Jakarta on-demand prices are from AWS's public price list files, read on 2026-10-30, before tax. The figures are monthly, over 730 hours.

| Item | Rate | Monthly |
|---|---|---:|
| **Core** | | |
| RDS `db.t4g.medium`, Single-AZ | $0.102/h | $74.46 |
| RDS gp3, 50 GB; backups beyond the free share | $0.138/GB-mo | about $8 |
| RDS master secret | $0.40 | $0.40 |
| Web: 0.25 vCPU, 0.5 GB | Fargate ARM $0.04045/vCPU-h, $0.00442/GB-h | $9.00 |
| API: 0.25 vCPU, 1 GB | | $10.61 |
| One ALB: three listeners, a few LCUs | $0.0252/h | about $21 |
| NAT gateway: hours, about 30 GB, its Elastic IP | $0.059/h, $0.059/GB, $0.005/h | about $49 |
| CloudFront (free tier), S3, ECR, Logs, alarms | | about $10 |
| **Core subtotal** | | **about $183** |
| **Ingestion** | | |
| Airflow: 0.5 vCPU, 3 GB | | $24.44 |
| Connector, platform and refresh tasks | about 100 task-hours a month | about $6 |
| EFS: about 9 GB, mostly IA, with backups | $0.36 Standard, $0.0272 IA per GB-mo | about $4 |
| MinerU g5.xlarge: today's window (about 85 h) **or** tightened (about 50 h) | $1.408/h | $120 **or** $70 |
| MinerU disk in the warm pool, image in ECR | | about $12 |
| **Ingestion subtotal** | | **about $166, or $116 tightened** |
| **Retrieval** | | |
| Gateway: 2 vCPU, 6 GB, always on **or** working hours (about 242 h) | $0.1074/h | $78 **or** $26 |
| Refresh, weekly | | under $1 |
| **Retrieval subtotal** | | **$27–79** |
| **Total** | | **about $326–428** |

**What moves the total:**
- **MinerU's window** is the largest lever ($50).
- **The gateway's hours** come next ($52).
- **A 1-year RDS reservation and a Compute Savings Plan for Fargate** take a further 20–30% off the steady parts. Buy them after two months of stable use, never before.
- **The NAT gateway** is the price of private subnets and one egress address. A NAT instance (`fck-nat` on `t4g.nano`, about $8 with its address) would save $40 a month. It is a single instance we would patch, so this plan doesn't take that trade.

## 7. Permissions to request

### 7.0 What the account allows on 2026-10-30, and what is still missing

**How this was read:** from the `Project3Learner` role's inline policy (`AwsSSOInlinePolicy`). `Project3CloudFormationRole`, `Project3EcsTaskExecutionRole` and `Project3StepFunctionsRole` carry the same ceiling, so deploying through them widens nothing.

**Since 2026-10-23,** RDS for PostgreSQL is allowed: engine `postgres`, classes up to `db.*.large`. The core moves to it without any request.

**Still missing,** with what each blocks:

| Missing | Blocks | Ask for |
|---|---|---|
| `elasticfilesystem:*` | The connectors' state (SQLite stores, PDFs, MinerU caches) on EFS: **all of ingestion** | `elasticfilesystem:*` on resources tagged `Owner=project3`, including `TagResource` and `CreateAccessPoint` |
| `iam:CreateRole`, `PutRolePolicy`, `AttachRolePolicy`, `DeleteRole*`, `TagRole` | Airflow's task role (`ecs:RunTask`, `iam:PassRole`). **No existing role may run ECS tasks**: `Project3EcsTaskExecutionRole` and `Project3StepFunctionsRole` allow neither `ecs:RunTask` nor `iam:PassRole` to ECS | Either these on `role/metamorph-*` with the boundary of [7.1](#71-the-full-set-for-a-fresh-start), or an administrator creating the roles `metamorph-airflow` (ecs:RunTask, DescribeTasks, StopTask on `metamorph-*`; iam:PassRole on the task roles) and `metamorph-connector` (EFS client, S3 inbox read) |
| `autoscaling:*` | MinerU's GPU Auto Scaling group and its ECS capacity provider | `autoscaling:*` on `metamorph-*` |
| `ec2:RunInstances` above `*.large` (`EC2LargeOrSmallerOnly`), and the G instance quota | MinerU on `g5.xlarge`, the only G instance in Jakarta | Allow `g5.xlarge`; quota `L-DB2E81BA` at 8 vCPUs |
| `servicediscovery:*` | MinerU's private name `mineru.metamorph.internal` | `servicediscovery:*` on namespace `metamorph.internal`, or keep MinerU behind an internal load balancer instead (allowed today) |
| `ec2:CreateInternetGateway`, `AttachInternetGateway`, `CreateNatGateway`, `AllocateAddress`, `AssociateAddress`, `ReleaseAddress` | The private VPC with one NAT gateway and one egress address ([§5.2](#52-network)). Until then everything stays in the default VPC's public subnets with a public IP per task | These, on resources tagged `Owner=project3` |
| `ssm:StartSession` and `ssmmessages:*`, for the people and for the task role | SSM port forwarding: Airflow's UI and the retrieval gateway from a laptop | `ssm:StartSession` on `arn:aws:ecs:ap-southeast-3:<account>:task/metamorph/*` and the `AWS-StartPortForwardingSession*` documents; `ssmmessages:*` on the gateway's and Airflow's task role |
| `backup:*` | AWS Backup plans for EFS and the monthly RDS snapshots | `backup:*` on `metamorph-*` vaults and plans (RDS's own automated backups work without it) |

Without the first three rows, ingestion can't run on AWS at all. The rest have workarounds or can wait.

### 7.1 The full set, for a fresh start

Ask the account's administrator for the following. Each is scoped to Metamorph's names, and each says what it is for.

**1. Lift the two RDS SCPs, or exempt this account from them.** (Done for RDS instances on 2026-10-30; see 7.0.) They are `AuroraEnginesOnly` and `AuroraServerlessV2Only`. They should allow:
- engine `postgres`;
- instance classes `db.t4g.medium`, `db.t4g.large` and `db.m7g.large`.

**2. A CloudFormation service role, `metamorph-cfn-exec`,** trusted by `cloudformation.amazonaws.com`, with:

| Service | Actions | Scope |
|---|---|---|
| EC2 / VPC | VPC, subnets, route tables, internet and NAT gateways, Elastic IPs, VPC endpoints, security groups, flow logs, launch templates (create, modify, delete, tag) | the region; tag `Project=metamorph` on create |
| ECS | `*` | cluster `metamorph`, `metamorph-*` task definitions and services |
| ECR | repository management | `metamorph/*` |
| Elastic Load Balancing | `*` | `metamorph-*` |
| RDS | instances, parameter and subnet groups, snapshots | `metamorph-*` |
| Secrets Manager | what RDS needs to manage its master secret | `rds!*` secrets |
| Systems Manager | `PutParameter`, `DeleteParameter`, `AddTagsToResource` | `/metamorph/prod/*` |
| EFS | `*`, **including `TagResource`** | file systems tagged `Project=metamorph` |
| Cloud Map | `*` | namespace `metamorph.internal` |
| Auto Scaling, Application Auto Scaling | `*` | `metamorph-*` |
| CloudWatch, Logs, EventBridge, EventBridge Scheduler, SNS | `*` | `metamorph*` names |
| AWS Backup | plans, selections, vaults | `metamorph-*` |
| CloudFront | distributions, VPC origins | the account |
| Budgets | create and modify | `metamorph` |
| IAM | `CreateRole`, `PutRolePolicy`, `AttachRolePolicy`, `DeleteRole*`, `TagRole`, `CreateServiceLinkedRole` | `role/metamorph-*`, **only with the condition `iam:PermissionsBoundary = …:policy/metamorph-boundary`** |
| IAM | `PassRole` | `role/metamorph-*` |

**3. The boundary policy, `metamorph-boundary`,** created by the administrator. It is the ceiling for every role the stacks create, and holds the union of the roles in [§5.6](#56-security-and-iam):
- S3 on the `metamorph-*` buckets, with no `DeleteObject` on blobs;
- `ssm:GetParameters` on `/metamorph/prod/*`;
- Logs;
- ECR pull;
- `elasticfilesystem:Client*`;
- ECS RunTask, Describe, Stop and UpdateService on `metamorph` resources;
- `iam:PassRole` on `role/metamorph-*`;
- `ssmmessages:*`, for ECS Exec;
- `cloudwatch:PutMetricData`;
- `secretsmanager:GetSecretValue` on the RDS secret;
- KMS decrypt through SSM and RDS.

**4. The deployer's own permissions** (a permission set, say `MetamorphDeployer`, for the owner):
- `cloudformation:*` on `stack/metamorph-*`, and `iam:PassRole` on `metamorph-cfn-exec`;
- read-only access (`ReadOnlyAccess`, or the describes above);
- ECR push to `metamorph/*`;
- `ecs:RunTask` and `ecs:ExecuteCommand`, and `ssm:StartSession` for port forwarding to the cluster's tasks;
- S3 on the ops bucket;
- `ce:*` reads and budgets.

**5. Team access** for Friend 1 and Friend 2:
- `ssm:StartSession` port forwarding to the gateway task;
- S3 read of `exports/`.

**6. A quota:** *Running On-Demand G and VT instances* (`L-DB2E81BA`), 8 vCPUs. Request it days ahead.

**7. To confirm, not request:**
- an organization CloudTrail exists;
- ACM in us-east-1 still works, since CloudFront's certificate stays there.

## 8. The implementation plan

Each phase ends at a gate; don't start the next until it passes. Effort is for one person, part-time, and is an estimate.

### Phase 0: access and facts (1–2 days)

1. **Request the permissions** in [§7](#7-permissions-to-request) and the quota.
2. **Sign in again** (`aws sso login`) and record the live state:
   - the stacks;
   - the Aurora cluster's version and size;
   - the ECR tags in use;
   - whether curators changed anything on AWS since 2026-10-23: `select action, count(*) from curation.audit_log where at > '2026-10-23' group by 1`, through a `metamorph-dbops` task.
3. **Check what Jakarta offers:**
   - the newest RDS PostgreSQL 16 minor and its pgvector version: `describe-db-engine-versions`. The Mac's is 0.8.7, and the index uses only exact `<=>` search, so any 0.7+ works;
   - g5.xlarge in at least one of the two zones;
   - the ECS GPU-optimized AMI's NVIDIA driver, which must be 580 or newer.
4. **Check whether the OJK connector still reads `~/.config/ojk-connector/credentials`** since its move to JDIH OJK. If not, drop that access point.

**Gate:**
- the permissions are granted;
- the facts are recorded in this document's [§3](#3-where-we-are);
- the curation delta is known: none, or a list.

### Phase 1: templates and code (4–6 days, on the Mac)

The work list is in [§9](#9-code-and-template-changes). Tests first, as everywhere: `tests/test_deploy_layers.py` grows to cover the new stacks and their exports. `cfn-lint` and `validate-template` pass on every template.

**Gate:**
- every repository's tests pass;
- `cfn-lint` is clean;
- the images build for arm64 and run on the Mac's compose stack with the new settings (call log on stdout, model baked in);
- the eval still gives 52/54 locally.

### Phase 2: network, foundation, database (1 day)

1. `deploy prod/network`, then `deploy prod/foundation`. Foundation adopts the existing ECR repositories and buckets:
   - first deploy the old `metamorph-foundation` with `DeletionPolicy: Retain` on them;
   - remove them from the old template;
   - import them into `metamorph-prod-foundation` with a change set of type `IMPORT`.
2. `deploy prod/database`. Then, through a `metamorph-dbops` task:
   - create the `airflow` and `bi` databases and the login roles of [§5.3](#53-the-core-web-api-database);
   - `CREATE EXTENSION vector`.
3. Write the parameters under `/metamorph/prod/`: database URLs per role, the curators, the web secret, the webhook.
4. Note the NAT's Elastic IP.

**Gate:**
- a `metamorph-dbops` task connects over TLS as each role;
- `select extversion from pg_extension where extname='vector'` answers;
- a task in a private subnet reaches `https://www.ojk.go.id` through the NAT, and its address is the Elastic IP.

### Phase 3: data (1 day; the curation freeze starts here)

1. **Freeze curation on AWS.** Tell the curators, and set the AWS web service to 0.
2. **The curation delta,** if Phase 0 found one: dump the AWS `curation` schema, compare it with the Mac's, and apply the missing decisions on the Mac through the API, so the audit log records them. Then `metamorph build` on the Mac.
3. **Dump the Mac:**
   - `metamorph`, whole: every schema, including `retrieval_market` with its embedding cache and active version;
   - `bi`.
   Upload both to `s3://metamorph-ops-<account>/transfer/`.
4. **Restore into RDS** with `metamorph-dbops` (`--no-owner --no-privileges`), then grant to the roles. Run `metamorph db migrate` with `metamorph-cli`; the database should already be at migration 22.
5. **Blobs:** `aws s3 sync` from SeaweedFS to the kept blobs bucket. Only the objects added since 2026-10-23 move: the keys are content addresses.

**Gate:** the counts on RDS equal the Mac's:

| Table | Must equal the Mac's |
|---|---|
| `published.document` | yes |
| `published.provision_unit` | yes |
| the `published_market` tables | yes |
| `curation.override` | 68 |
| `curation.review_item` | yes |
| `retrieval_market.unit` | 7,022, under the active version |

`metamorph health` exits 0.

### Phase 4: core cut-over (half a day)

1. Push `platform` and `curation-web` at their current commits.
2. `deploy prod/api`, then `deploy prod/web`. The new CloudFront distribution needs the curation host name:
   - move the alias from the old distribution (CloudFront's alias move, or remove and add: minutes of downtime, announced);
   - the DNS CNAME doesn't change;
   - the certificate is reused.
3. Run the old guide's Phase 6 checks against the new stack, plus the market curation pages.

**Gate:**
- every check passes;
- the curators sign in and see the same counts;
- unfreeze curation.

**Then retire the old stack:**
- keep Aurora stopped for 14 days, with a final snapshot kept 90 days;
- delete `metamorph-web`, `metamorph-api`, `metamorph-database` and `metamorph-foundation`, minus the adopted resources.

### Phase 5: ingestion and MinerU (2–3 days)

1. `deploy prod/ingestion-shared`.
2. **The connectors' data into EFS:**
   - tar each of the nine repositories' `data/`, without `exports/`;
   - upload the tarball to `transfer/`;
   - unpack it with a `metamorph-ops` task.

   **Check the MinerU caches' sizes against the Mac's** (190 MB in all).
3. Push the nine connector images and Airflow. `deploy prod/ingestion-jobs`.
4. `deploy prod/ingestion-mineru`. On the GPU instance, held in service:
   - `nvidia-smi` shows a driver of 580 or newer;
   - build and push `metamorph/mineru:4.0.12`;
   - read the two step 9 PDFs with `mineru_check.py` from a BPK task.

   **They must match their cached readings.**
5. `deploy prod/ingestion-airflow`, with every DAG paused. Open the UI through SSM port forwarding.
6. **Run each DAG once by hand, in the window, one at a time,** regulation connectors first:
   - each run should find little or nothing new, since the Mac ran last;
   - each load must succeed;
   - `registry_build` and `market_publish` must follow.

   **If a source refuses** (403, 429, a challenge): stop that connector and leave its DAG paused. Never vary headers or addresses.
7. Unpause the DAGs, except `ingest_bps_stats` ([§4.3](#43-other-findings) #10).

**Gate:**
- a week of scheduled runs with no unexplained failure;
- `health` passes daily;
- the MinerU window opens and closes on time (the ASG's activity history);
- the published counts grow only by what the sources added.

**Then:**
- tighten the window, after two weeks of durations;
- the Mac goes back to being a development stack, its DAGs paused for good.

### Phase 6: retrieval (1–2 days)

1. Push `metamorph/retrieval:<commit>`, with the model baked in. `deploy prod/retrieval`.
2. Run the refresh once by hand, as the `market_index` DAG would. Because the cache came across, it should embed nothing new and keep or re-activate an equivalent version.
3. Run the eval from a task in the VPC against `http://<ALB>:8765`. Run it again through SSM port forwarding from the Mac.
4. Unpause `market_index`.
5. Give Friend 1 the SSM recipe in [docs/connecting-an-agent.md](../../Metamorph-Retrieval/docs/connecting-an-agent.md).

**Gate:**
- 52/54;
- p95 under 500 ms over the eval's calls;
- after a `market_publish`, the refresh runs, its comparison is in the logs, and the gateway serves the new version without a manual restart.

### Phase 7: hardening (1–2 days)

1. `deploy prod/observability`: dashboard, alarms, the ECS failure rule, budget, Cost Anomaly Detection, Backup plan.
2. **Practise, once each, and write down the steps:**
   - restore RDS to a point in time, into a scratch instance;
   - restore one connector's `data/` file from EFS backup;
   - roll back an image tag on the API;
   - stop and start everything for a night.
3. Rewrite [aws-deployment-guide.md](aws-deployment-guide.md) as the runbook for the new stack, and update [deploy/aws/ingestion/README.md](../deploy/aws/ingestion/README.md).

**Gate:**
- each alarm has fired once on purpose and reached email and Slack;
- each restore worked.

**From here it is production.**

### Phase 8: later, when there is a reason

| What | Trigger |
|---|---|
| GitHub Actions with OIDC | More than one person deploys |
| Multi-AZ RDS | Retrieval serves end users |
| Reservations and Savings Plans | Two months of stable use |
| Public access to retrieval: bearer token, then API Gateway | An agent outside AWS calls it unattended |
| ADOT and X-Ray | The agent runs on AWS |
| WAF | The curation address is widely known |
| A staging copy | Changes start breaking production |

## 9. Code and template changes

These are small and outermost: wiring, adapters and templates. None touches a domain or application ring, except the gateway's active-version refresh, which is an adapter of the market provider.

| Repository | Change | Why |
|---|---|---|
| Platform `deploy/aws/` | New `prod/` templates per [§5.9](#59-infrastructure-as-code-and-delivery):<br>- network;<br>- RDS instead of Aurora;<br>- the shared ALB with a listener per service stack;<br>- roles per family under the boundary;<br>- `Fn::ForEach` over the nine connectors;<br>- the SEKI inbox init container;<br>- retrieval;<br>- observability.<br>`push-images.sh`: tag by commit; all twelve images. Tests in `tests/test_deploy_layers.py` | [§5](#5-the-target-architecture) |
| Platform `dags/` | `ingest_reports` moves into MinerU's window. A test checks every MinerU-reading job starts inside the window's parameters. Until the gateway's TTL lands, `market_index` restarts `retrieval-gateway` after a successful refresh, under the ECS launcher only | [§4.3](#43-other-findings) #2, #4 |
| Retrieval, market provider adapter | Resolve the active index version on a TTL (60 s); reconnect after a lost connection | [§4.3](#43-other-findings) #4 |
| Retrieval gateway | `/health` checks the providers' database. A stdout call log adapter (JSON lines with EMF fields), chosen by `METAMORPH_RETRIEVAL_CALL_LOG=stdout` | #4, #5 |
| Retrieval `Dockerfile` | Bake bge-m3 at a pinned revision (`HF_HUB_OFFLINE=1` at run time) | #6 |
| Retrieval `scripts/refresh-market-index.sh` | Print the comparison to stdout. Take the indexer's URL from `METAMORPH_RETRIEVAL_INDEX_DATABASE_URL` | #5, [§5.3](#53-the-core-web-api-database) |
| Retrieval `docs/connecting-an-agent.md` | The SSM port-forwarding recipe | [§5.5](#55-retrieval-for-market-data) |
| Each connector's README | The egress Elastic IP | #1 |

**Not changed:**
- the connectors' code;
- the parser and extraction;
- the published schemas;
- the contract.

## 10. Risks

| Risk | Likelihood | What happens | Mitigation |
|---|---|---|---|
| A source blocks AWS's address range | Medium | A connector's collect fails with a refusal | Phase 5 runs each by hand first. On a refusal, stop that connector and decide with the owner. Never vary headers or addresses to get through |
| The SCP exemption is refused | Low–Medium | No RDS | Fallback: Aurora Serverless v2 with a **1 ACU floor**, no pause, about $146 plus I/O. Everything else in this plan is unchanged |
| No g5.xlarge capacity in the window | Low | Connector tasks needing MinerU fail and retry | The warm pool holds an instance. Alarm on the window not opening. Runs succeed the next day; nothing is half read |
| Graviton CPU makes retrieval slower than the Mac | Medium | p95 over 500 ms | Use 4 vCPU (+$59 always on). Then consider ONNX or int8 bge-m3. Re-evaluate before changing the model |
| The curation delta is non-trivial | Low | Phase 3 takes longer | It is found in Phase 0, before the freeze |
| The image (5.7 GB) slows task starts | Medium | The refresh starts a minute later | Harmless for a weekly task. SOCI lazy loading if it ever matters |
| SQLite on EFS under concurrent writers | Low | A corrupted connector store | One run per DAG, and no person runs a connector's CLI against EFS while its DAG is unpaused. EFS backups |

## 11. Decisions for the owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | RDS `db.t4g.medium` Single-AZ instead of Aurora | **Yes,** with Aurora at a 1 ACU floor as the fallback if the SCP stays |
| 2 | A new VPC with one NAT gateway, against staying public at about $40 less a month | **The new VPC:** one egress address matters for the sources |
| 3 | The gateway's hours: always on ($78) or working hours ($26) | **Working hours** while Friend 1 evaluates; always on when an agent serves people |
| 4 | Move `ingest_reports` into MinerU's window, or widen Monday's window (+$13 a month) | **Move it** |
| 5 | Keep Airflow, rather than MWAA or Step Functions | **Keep it** |
| 6 | Keep CloudFormation, with a service role and boundary | **Keep it** |
| 7 | WAF and GuardDuty now or later | **Later**, per Phase 8 |
