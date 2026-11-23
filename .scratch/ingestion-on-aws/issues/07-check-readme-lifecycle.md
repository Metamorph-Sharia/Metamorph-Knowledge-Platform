# 07 The check command, the README deployment order, backup expiry

Status: resolved
Blocked by: 02, 03, 04, 05, 06

Spec: `../spec.md`, Testing Decisions "Seam 2", the "Deployment order" and "The gate" decisions, and user story 32.

## What to build
- **A `check.sh` in the ingestion deploy directory**, modeled on mira-ai-chatbot's `deploy/langfuse/aws/check.sh`. Read-only AWS CLI calls that report pass or fail for:
  - the five roles and the instance profile exist, each trusted by the right service;
  - the ingestion stacks are complete;
  - EFS has its access points;
  - the MinerU instance is stopped outside the window;
  - the Airflow service has a running task.
- **The ingestion README:** rewrite it as the deployment order and gate from the spec. Remove the superseded notes, including the IAM table, which now points to `docs/aws-ingestion-permissions.md`.
- **The core's foundation template:** add a lifecycle rule expiring the ops bucket's `backups/` after 35 days, beside its existing rules.
- Remove the `xfail` mark from the "no IAM in ingestion templates" test (ticket 02).

## Acceptance
- The full test suite passes, including the no-IAM test without `xfail`.
- `bash -n check.sh` is clean.

## Comments

2026-11-23: implemented on branch `ingestion-on-aws` (merge of `t07-*`); review fixes in the "Merge review fixes" commit.
