# 04 MinerU: one scheduled g5.xlarge behind an internal ALB

Status: resolved
Blocked by: 01, 02

Spec: `../spec.md`, the decision "The MinerU stack replaces the Auto Scaling design", and user stories 13–21. Notes: see ticket 02.

## What to build
Rewrite the MinerU stack template:
- **Remove:** the Auto Scaling group, the warm pool, the launch template, the capacity provider and its association, Cloud Map, and every IAM resource.
- **The instance:** an `AWS::EC2::Instance`.
  - Type `g5.xlarge`, from the ECS GPU AMI parameter.
  - Root volume of at most 100 GB, and a public IP.
  - Instance profile parameter, default `metamorph-mineru-instance`.
  - Tags `Name=metamorph-mineru` and `Owner=project3`.
  - User data joins cluster `metamorph` and sets a custom attribute, with GPU support enabled.
- **The MinerU ECS service:** EC2 launch type, placement constraint on that attribute, desired count 1, registered with an internal ALB target group. The health check follows MinerU's health endpoint; see `docker/mineru` and the existing template.
- **The URL parameter:** export or write the ALB's address into the connectors' MinerU URL parameter.
- **Scheduler:** three schedules with the universal EC2 target (`arn:aws:scheduler:::aws-sdk:ec2:startInstances` / `stopInstances`), using role parameter `SchedulerRole` (default `metamorph-scheduler`):
  - a daily start, a few minutes before the window;
  - a daily stop;
  - a later stop on the 1st of the month.
- **The window as parameters:** start at about 00:20, end at 03:15, monthly end at 04:30 UTC.

Tests go in `tests/test_ingestion_stacks.py`:
- every DAG job with the PDF flag (from ticket 01) has a cron start inside the window that the template's parameters define, and the monthly runs on the 1st fall before the monthly end;
- the instance has no Auto Scaling group and no IAM resource.

Update `deploy/aws/ingestion/README.md`'s MinerU steps to match.

## Acceptance
- The full test suite passes.
- `cfn-lint` is clean.

## Comments

2026-11-23: implemented on branch `ingestion-on-aws` (merge of `t04-*`); review fixes in the "Merge review fixes" commit.
