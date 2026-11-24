# AWS permissions for the ingestion layer

**For:** the DevOps team. **Account:** 129712841299, region `ap-southeast-3` (Jakarta). **Date:** 2026-11-23.

We need to deploy the ingestion layer: nine source connectors, Apache Airflow, and the MinerU OCR service. The rest of the system (Knowledge Platform, Retrieval, the MIRA chatbot) already runs on ECS in this account. Ingestion is blocked because we cannot create IAM roles and a few services are missing from our permission set.

We **do not ask for `iam:CreateRole`**. We ask you to create five roles, add a small set of permissions to `Project3Learner`, and raise one quota. Every policy is ready to apply in [`deploy/aws/iam/`](../deploy/aws/iam/).

> **Update, 2026-11-24:** the connectors now run off AWS (sources refuse AWS addresses: [ADR 0001](adr/0001-collection-on-a-residential-host.md)), so the nine connector tasks, EFS and the `metamorph-connector-task` role below are retired once the cutover passes ([deploy/aws/ingestion/README.md](../deploy/aws/ingestion/README.md)). The rest of this request stands: Airflow, the platform task, MinerU and its roles.

## What we will deploy

All of it goes in the default VPC, through CloudFormation run as `Project3Learner`, and is tagged `Owner=project3`.

| Part | AWS resources |
|---|---|
| 9 connectors | ECS Fargate tasks (0.5–1 vCPU, 2 GB), started by Airflow |
| Platform load and build | ECS Fargate tasks (1 vCPU, 4 GB) |
| Airflow 2.10 | One ECS Fargate service (0.5 vCPU, 3 GB); its metadata in the existing RDS `metamorph-pg` |
| Connector state | One EFS file system with an access point per connector |
| MinerU (OCR) | One `g5.xlarge` EC2 instance, registered to ECS cluster `metamorph`, started and stopped by EventBridge Scheduler around the nightly window; reached through an internal ALB |
| Airflow UI | An internal ALB in front of Airflow, published through CloudFront (VPC origin). A CloudFront Function asks for a password (HTTP Basic auth) and checks its sha256 before any request reaches Airflow's own sign-in. A WAF rate limit sits in front. This is the same pattern as our dev retrieval gateway, and all of it is allowed today |
| Alerts | An EventBridge rule on failed tasks, sending to SNS |
| Backup | A weekly ECS task copying the connector data to S3 bucket `metamorph-ops-129712841299` |
| Images | ECR repositories `metamorph/*` |

`Project3Learner` already allows ECS, ECR, EC2 (up to `*.12xlarge`), ELB, CloudFront, WAF, EventBridge, Scheduler, SNS, S3, Logs, Parameter Store, CloudFormation and `iam:PassRole`. Nothing more is needed for those.

## Checklist

### 1. Add to the `Project3Learner` permission set

Policy: [`learner-additions.json`](../deploy/aws/iam/learner-additions.json).

- [ ] **EFS:** create a file system and access points tagged `Owner=project3`, and manage only those.
- [ ] *(Optional)* **Read Service Quotas**, so we can check the GPU quota ourselves.

### 2. Create these roles

All five roles are named exactly as below, because our templates reference them by name. Tag each one `Owner=project3`.

| Role | Trust policy | Permissions policy | What it is for |
|---|---|---|---|
| [ ] `metamorph-airflow-task` | [`trust-ecs-tasks.json`](../deploy/aws/iam/trust-ecs-tasks.json) | [`metamorph-airflow-task.json`](../deploy/aws/iam/metamorph-airflow-task.json) | Airflow starts, watches and stops the `metamorph-*` tasks in cluster `metamorph` and reads their logs. It may pass only the three task roles it launches with, and it may restart the retrieval gateway after an index refresh |
| [ ] `metamorph-connector-task` | `trust-ecs-tasks.json` | [`metamorph-connector-task.json`](../deploy/aws/iam/metamorph-connector-task.json) | The connectors mount our EFS file system. They read `inbox/` from the ops bucket, and read and write its `transfer/` and `backups/` prefixes |
| [ ] `metamorph-platform-task` | `trust-ecs-tasks.json` | [`metamorph-platform-task.json`](../deploy/aws/iam/metamorph-platform-task.json) | Load and build read bundles from EFS and write to the blobs bucket. They cannot delete |
| [ ] `metamorph-scheduler` | [`trust-scheduler.json`](../deploy/aws/iam/trust-scheduler.json) | [`metamorph-scheduler.json`](../deploy/aws/iam/metamorph-scheduler.json) | EventBridge Scheduler starts and stops the one instance tagged `Name=metamorph-mineru` |
| [ ] `metamorph-mineru-instance`, **with an instance profile of the same name** | [`trust-ec2.json`](../deploy/aws/iam/trust-ec2.json) | AWS managed `AmazonEC2ContainerServiceforEC2Role` | The GPU instance joins the ECS cluster and pulls the MinerU image |

Notes:
- The task *execution* role (image pull, logs, secrets) stays the existing `Project3EcsTaskExecutionRole`. No new execution role is needed.
- The EFS conditions match a file system tagged `Owner=project3` and `Project=metamorph`. We will tag it that way.
- One connector role covers all nine connectors. Each task mounts only its own access point, but IAM does not stop one connector from mounting another's. See "Optional, later" below.

### 3. Raise a quota

- [ ] **Running On-Demand G and VT instances** (`L-DB2E81BA`) in `ap-southeast-3`: **8 vCPUs** (one `g5.xlarge` needs 4). Please request it early, since approval can take days.

### 4. Please confirm

- [ ] The SCPs allow `g5.xlarge` in `ap-southeast-3`. Our inline policy now allows up to `*.12xlarge`.
- [ ] An organization CloudTrail covers this account.

## What we can do once this is in place

| Granted | Unblocks |
|---|---|
| Section 1 (EFS) and the three task roles | Connectors, platform tasks and Airflow. Scanned PDFs wait for MinerU |
| Quota, `metamorph-scheduler` and `metamorph-mineru-instance` | MinerU, so OCR works and ingestion goes live in full |

## Optional, later

None of these is needed to deploy.

- SSM port forwarding (`ssm:StartSession` on tasks in cluster `metamorph`, and `ssmmessages:*` on `metamorph-airflow-task`), if you prefer the Airflow UI to have no public address at all.

- A scoped execution role, `metamorph-exec`, limited to `/metamorph/*` parameters, in place of the shared `Project3EcsTaskExecutionRole`.
- Nine per-connector roles, each allowed only its own EFS access point, if you want strict isolation between connectors.
- AWS Backup (`backup:*` and a backup service role) for EFS, in place of our weekly copy to S3.
- A private VPC with one NAT gateway and a fixed egress IP (`ec2:CreateInternetGateway`, `CreateNatGateway`, `AllocateAddress` and related actions), if a source starts allowing or blocking by IP.
- **Instead of section 2:** give us `iam:CreateRole`, `PutRolePolicy`, `AttachRolePolicy`, `DeleteRole*`, `TagRole` and `CreateInstanceProfile` on `role/metamorph-*`, on condition that every role carries a permissions boundary that you own. Our stacks would then create these roles themselves.
