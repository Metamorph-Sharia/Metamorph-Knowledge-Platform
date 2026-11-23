# 06 Alerts stack: failed tasks and a dead Airflow, to email

Status: resolved
Blocked by: none

Spec: `../spec.md`, the decision "Alerts", and user stories 27–29.

## What to build
A new ingestion stack template for alerts:
- an SNS topic with an email subscription (`AlertEmail` parameter) and a topic policy that lets EventBridge publish;
- an EventBridge rule on `ECS Task State Change` with `lastStatus=STOPPED`, a non-zero container exit code, cluster `metamorph`, and task definition family `metamorph-*`, sending to the topic;
- a CloudWatch alarm when the `airflow` service's running task count (Container Insights, or the ECS `RunningTaskCount` metric) is below 1 for 10 minutes. Pick a metric that exists without Container Insights if you can, and document the choice.
- No IAM resources. Tag everything `Owner=project3`.

Add the stack to the README's deployment order.

A test in `tests/test_ingestion_stacks.py`: the rule matches only stopped tasks with non-zero exits in our cluster.

## Acceptance
- The full test suite passes.
- `cfn-lint` is clean.

## Comments

2026-11-23: implemented on branch `ingestion-on-aws` (merge of `t06-*`); review fixes in the "Merge review fixes" commit.
