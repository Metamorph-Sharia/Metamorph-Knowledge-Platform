# Spec: the ingestion layer on AWS

Status: ready-for-agent

## Problem Statement

The ingestion layer runs only on the owner's Mac. That layer is the nine source connectors, Airflow, the platform's load and build tasks, and MinerU for OCR. The Knowledge Platform, Retrieval and the MIRA chatbot already run on AWS, but the corpus they serve is refreshed only when the Mac runs its DAGs. When the Mac is off, the sources' new regulations and statistics never reach the platform.

The AWS templates for ingestion were written before we knew the account's limits, and they cannot be deployed:
- They create IAM roles, and our role cannot.
- They put MinerU on an Auto Scaling group with Cloud Map, and both are denied.
- They cover only four of the nine connectors.

DevOps has now granted everything in the permission checklist (`docs/aws-ingestion-permissions.md`): five roles, an instance profile, EFS on our SSO role, and a GPU quota of 32 vCPU. Nothing blocks deployment except the templates themselves.

## Solution

Ingestion runs on AWS every night without the Mac:
- **Airflow** runs as an ECS service and starts each connector, load, build and publish step as an ECS task.
- **Connector state** lives on EFS: the SQLite stores, PDFs and MinerU caches.
- **MinerU** runs on one `g5.xlarge` that EventBridge Scheduler starts before the ingest window and stops after it. Connectors reach it through an internal load balancer.
- **The Airflow UI** is reached in a browser through CloudFront. A password check runs at the edge, before Airflow's own sign-in.
- **Failures** reach the owner by Slack and email.
- **Connector data** is copied to S3 every week.

Every role comes from DevOps by name. No stack creates an IAM resource.

Once it runs, the Mac goes back to being a development stack with its DAGs paused.

## User Stories

1. As the owner, I want every connector to run on AWS on its schedule, so that the corpus stays fresh when my Mac is off.
2. As the owner, I want all nine connectors deployed (OJK, BPK, BI, DSN-MUI, OJK register, OJK statistics, BI statistics, BPS statistics, Reports), so that no source is left behind on the Mac.
3. As the owner, I want each connector's state (its SQLite store, PDFs and MinerU cache) kept on EFS between runs, so that a run collects only what is new.
4. As the owner, I want each connector to mount only its own directory on EFS, so that one connector cannot overwrite another's store by mistake.
5. As the owner, I want the connectors' data moved from the Mac to EFS once, without `exports/`, so that AWS starts where the Mac left off and doesn't re-collect or re-OCR the corpus.
6. As the owner, I want to compare the MinerU caches' sizes on EFS against the Mac's after the move, so that I know the costly OCR readings arrived intact.
7. As the owner, I want a load to follow every successful collect, and the registry build or market publish to follow every load, so that new documents reach `published` and `published_market` without manual steps.
8. As the owner, I want the market index refreshed after market publish, as it is locally, so that retrieval sees new statistics.
9. As the owner, I want Airflow's metadata kept in its own `airflow` database on the existing RDS instance, so that I pay for no new database.
10. As the owner, I want Airflow to run tasks only through the `metamorph-airflow-task` role, so that what it can do in AWS is limited to running our task definitions.
11. As the owner, I want every stack to take its roles by name as parameters, so that the templates deploy under an account where we cannot create roles.
12. As the owner, I want every ingestion task to use `Project3EcsTaskExecutionRole` as its execution role, so that image pulls, logs and secrets work as they do for the core.
13. As the owner, I want MinerU's GPU instance running only during the ingest window, so that I pay for about 1.5 to 3 hours a day rather than 24.
14. As the owner, I want the instance started a few minutes before the first PDF-reading DAG and stopped after the last one's window ends, so that no OCR request finds MinerU down.
15. As the owner, I want a longer window on the 1st of the month, so that the monthly runs fit inside it.
16. As the owner, I want every DAG that reads PDFs to start inside MinerU's window, checked by a test, so that a schedule change can't silently send OCR work to a stopped instance.
17. As the owner, I want `ingest_reports` moved into the window, so that the Reports connector's PDFs are read by MinerU.
18. As a connector, I want MinerU's address from a setting that names the internal load balancer, so that I don't need to know which instance serves it.
19. As a connector, I want a clear `ExtractionUnavailable` failure when MinerU isn't serving, so that the task fails and retries rather than reading a scan another way.
20. As the owner, I want one setting (`pdf-engine` = `pymupdf`) to roll every connector back, as it does today, so that a MinerU problem never stops born-digital ingestion.
21. As the owner, I want the MinerU image built off the GPU instance and pushed with my own credentials, so that the instance role only needs to pull.
22. As the owner, I want to open the Airflow UI in a browser through a CloudFront address, so that I can inspect and rerun DAGs without SSH or port forwarding.
23. As the owner, I want the browser to ask for a password at the edge, checked against a stored hash, so that no request reaches Airflow unauthenticated.
24. As the owner, I want Airflow's own sign-in kept behind that password, so that a leaked edge password alone doesn't grant control.
25. As the owner, I want a per-address rate limit in front of the Airflow UI, so that guessing passwords is slow.
26. As the owner, I want Airflow's links and redirects to use the CloudFront address, so that the UI works behind it.
27. As the owner, I want a Slack message when a DAG task fails, as Airflow already sends, so that I see failures where I work.
28. As the owner, I want an email when any ingestion task stops with a non-zero exit code, so that I hear about failures even if Airflow itself is broken.
29. As the owner, I want an email when Airflow's service has had no running task for 10 minutes, so that a dead scheduler doesn't go unnoticed for days.
30. As the owner, I want the daily `health` DAG to keep failing on critical staleness, so that a source that stopped updating is caught.
31. As the owner, I want a weekly DAG to copy every connector's data directory to the ops bucket's `backups/` prefix, under a dated key, so that I can rebuild EFS if it is lost.
32. As the owner, I want old weekly backups expired automatically after about 5 weeks, so that the bucket doesn't grow without limit.
33. As the owner, I want the BI statistics task to copy curator-dropped SEKI zips from the ops bucket's `inbox/` into its data directory before it runs, so that the SEKI flow works as it does locally.
34. As the owner, I want every resource tagged `Owner=project3`, and EFS also tagged `Project=metamorph`, so that the organization's policies allow it and our grants match it.
35. As the owner, I want the ingestion stacks to import only what the live core already exports, or what they export themselves, so that deploying ingestion never needs a core redeploy.
36. As the owner, I want a `check` command that confirms the roles exist with the right trust, the stacks are complete, the access points exist, and the GPU instance is stopped outside the window, so that I can verify a deploy in one step.
37. As the owner, I want to run each DAG once by hand inside the window, regulation connectors first, so that I can see every connector, load and build work on AWS before scheduling.
38. As the owner, I want a source that refuses AWS's addresses (403, 429, a challenge) to stop its connector and leave its DAG paused, so that we never vary headers or addresses to get around a refusal.
39. As the owner, I want the first night of scheduled runs to be the gate, with no week-long trial, so that I can go live without waiting a week.
40. As the owner, I want the following days watched by the alerts and `health` rather than by a blocking gate, so that later regressions are triaged, not chased.
41. As the owner, I want `ingest_bps_stats` left paused at go-live, as the plan says, so that its known issue doesn't add noise.
42. As the owner, I want to pause all DAGs and set `pdf-engine` back as the full rollback, with the Mac able to take over, so that a bad night costs nothing permanent.
43. As a future maintainer, I want the deployment steps written in the ingestion README in order, so that someone else can redeploy from nothing.
44. As DevOps, I want our templates to reference only the roles and resources we agreed, so that our grants stay the complete list of what Metamorph can do.

## Implementation Decisions

**Roles come in as names, never as resources.**
- The ingestion templates stop declaring every IAM role, managed policy and instance profile.
- Each takes the role it needs as a parameter, defaulting to the DevOps-provided names: `metamorph-airflow-task`, `metamorph-connector-task`, `metamorph-platform-task`, `metamorph-scheduler`, and `metamorph-mineru-instance` (role and instance profile).
- The execution role is the core's live export, which is `Project3EcsTaskExecutionRole`.
- The imports of the core's `metamorph-exec-policy` and `metamorph-platform-role` go away. The live core doesn't export them.
- The ops task runs as `metamorph-connector-task`. It mounts EFS and reads and writes `transfer/` and `backups/`.

**The shared ingestion stack:**
- Security groups for Airflow, the tasks, MinerU's load balancer, the GPU host and EFS, with rules into the core's database group.
- One EFS file system, encrypted, tagged `Owner=project3` and `Project=metamorph`, with a mount target in each default-VPC subnet. Access points:
  - one per connector, nine in all, each rooted at that connector's directory;
  - one for bundles.
  - The OJK credentials access point is kept only if the JDIH source still reads credentials. Check this first.
- ECR repositories for the nine connectors, Airflow and MinerU, with scan on push, immutable tags and a keep-last-10 lifecycle.
- The wiring parameters.
- Cloud Map is removed.

**The jobs stack:**
- One task definition per image that a DAG runs: nine connectors, the platform, and ops. Each family is named after its image, so `task_family` is unchanged.
- Each connector's task definition mounts only its own access point and the bundles access point.
- The BI statistics task definition keeps its non-essential first container, which copies `inbox/bi-seki/` into the connector's inbox.
- Sizes follow the plan: connectors 0.5–1 vCPU and 2 GB, platform 1 vCPU and 4 GB, all within the account's 2 vCPU / 8 GB task cap.

**The MinerU stack replaces the Auto Scaling design:**
- One EC2 instance, `g5.xlarge`, from the ECS GPU-optimized AMI (public SSM parameter).
- Root volume of at most 100 GB, the account's limit. A public IP in the default VPC, so it can reach ECR without NAT.
- Instance profile `metamorph-mineru-instance`, tagged `Name=metamorph-mineru` and `Owner=project3`.
- User data joins cluster `metamorph` with a custom attribute.
- The MinerU ECS service uses the EC2 launch type, with a placement constraint on that attribute and a desired count of 1. It places itself whenever the instance is running.
- An internal Application Load Balancer, with a target group whose health check follows MinerU's health endpoint, gives the connectors a stable address.
- **The window:** EventBridge Scheduler schedules use the `metamorph-scheduler` role and the universal EC2 target to start the instance before the window and stop it after. Three schedules: daily start, daily stop, and a later stop on the 1st of the month.
- Starting from stopped (with the image cached on the root volume) replaces the warm pool.
- **The window's times become parameters:**
  - start a few minutes before 00:30 UTC to allow boot and placement;
  - end at 03:15 UTC daily, 04:30 UTC on the 1st;
  - tighten after durations are measured.

**The Airflow stack:**
- Airflow 2.10 as a Fargate service: LocalExecutor, metadata in the `airflow` database on `metamorph-pg`, task role `metamorph-airflow-task`, `METAMORPH_TASK_LAUNCHER=ecs`, and the `METAMORPH_ECS_*` settings from the stack.
- **UI access copies the dev retrieval gateway's pattern:**
  - an internal ALB in front of the webserver;
  - a CloudFront distribution with a VPC origin;
  - a CloudFront Function that requires HTTP Basic auth and compares the password's sha256 with a hash given to the stack. The password itself lives in Parameter Store and never in the template.
  - a WAF rate-limit web ACL made by a script in us-east-1, because the organization denies CloudFormation there.
- Airflow's base URL is the CloudFront address.

**DAG jobs:**
- A connector job declares whether it reads PDFs, through a new boolean field on the job description. This is how the window test finds the DAGs that depend on MinerU.
- `ingest_reports` moves inside the window: Mondays, after DSN-MUI's 02:00 run. The DAG schedules and the MinerU stack's window parameters change together.
- A new weekly DAG runs the ops task. It tars each connector's data directory from EFS to `backups/<date>/` in the ops bucket.
- An S3 lifecycle rule on the ops bucket expires `backups/` after 35 days.
- Airflow runs the backup because the scheduler role may only start and stop EC2, so EventBridge cannot run ECS tasks.

**Alerts:**
- The Airflow failure webhook is read from Parameter Store, as designed.
- An EventBridge rule matches `ECS Task State Change` with `STOPPED` and a non-zero container exit code in cluster `metamorph`, for `metamorph-*` task families, and sends to an SNS topic with the owner's email.
- A CloudWatch alarm fires when the Airflow service's running task count is below 1 for 10 minutes.
- No role is needed: SNS topic policies allow the rule.

**Deployment order** (written into the ingestion README):
1. shared;
2. the Airflow database;
3. images;
4. jobs;
5. move the connectors' data;
6. MinerU, then build and push its image and check it against the step 9 PDFs;
7. Airflow with every DAG paused;
8. the WAF script, then the UI address;
9. each DAG once by hand;
10. unpause all DAGs except `ingest_bps_stats`.

**The gate:**
- every DAG passes one hand run inside the window;
- the `check` command passes;
- the first night of scheduled runs ends with no unexplained failure and `health` passing.

After that, alerts and `health` monitor without blocking.

**Rollback:**
- pause the DAGs;
- set `pdf-engine` to `pymupdf` for a MinerU-only fault;
- the Mac can resume, since its data is untouched until the AWS run is trusted.

The stacks can be deleted. EFS deletion is held back by its retention setting.

## Testing Decisions

A good test here checks what we deploy, as written in the templates and the DAG jobs. It does not check how a template is laid out. It must run offline in the existing test suite, with no AWS access.

**Seam 1: the templates against the DAG jobs.** This extends the existing deploy-layer test and reuses the `jobs` fixture from the DAG job tests. It asserts:
- no ingestion template declares an `AWS::IAM::*` resource;
- every role an ingestion template uses comes from a parameter;
- every image any DAG runs (including retrieval's refresh and ops) has a task definition whose family is `task_family(image)`;
- every connector job has its own EFS access point, and its task definition mounts that one and no other connector's;
- every job that reads PDFs has a schedule whose start falls inside the window defined by the MinerU stack's parameters, including the monthly window on the 1st;
- every import in the ingestion templates is exported by the core templates or the ingestion templates, and the core templates' exports match the live core's. That second part is a list kept beside the test, updated when the core changes.

The prior art is the existing deploy-layer test, which parses imports and exports with regular expressions, and the DAG job tests, which build the jobs and assert schedules, mounts and task families.

**Seam 2: the live `check` command** in the ingestion deploy directory. It runs after a deploy, not in CI, and reports:
- whether the five roles and the instance profile exist, each trusted by the right service;
- whether the four stacks are complete;
- whether EFS has its eleven access points;
- whether the MinerU instance is stopped outside the window, and whether the Airflow service has a running task.

The prior art is the Langfuse stack's `check` command in mira-ai-chatbot.

No new test seam goes into the operators. The ECS launcher in `containers.py` is already covered and does not change.

## Out of Scope

- A private VPC with NAT and a fixed egress address.
- AWS Backup, a scoped `metamorph-exec` role, and per-connector roles.
- Spot instances for MinerU.
- Tightening the window. That follows two weeks of measured durations.
- MWAA, Step Functions, and any change to the DAGs' orchestration.
- A week of scheduled runs as a go-live gate.
- A curation-web upload page for SEKI zips.
- Removing the dev retrieval gateway's public access.
- Re-OCR of the corpus on AWS. The moved MinerU caches are reused.
- `ingest_bps_stats` going live.

## Further Notes

- **The granted policies are slightly broader than requested:** region `*`, no tag conditions on EFS mount, no `Owner` condition in the scheduler role. They are recorded as granted in `deploy/aws/iam/`. Nothing in this spec depends on the narrower versions.
- **The organization's policy denies every create without `Owner=project3`.** An untagged create fails as "explicit deny in a service control policy", which looks like a missing permission but is not one.
- **EFS created by CloudFormation must carry the tag in the create call**, or the learner role's `EfsCreateWithOwnerTag` deny fires.
- **The two SageMaker-managed EFS file systems in the account are not ours.** Leave them alone.
- **Our rule if a source refuses AWS's addresses:** stop, and never vary headers or IPs.
- **Rough cost:**
  - Airflow about $28 a month;
  - tasks about $3;
  - EFS about $2;
  - the GPU about $70–130, depending on window length;
  - the CloudFront and WAF in front of the UI about $8.
