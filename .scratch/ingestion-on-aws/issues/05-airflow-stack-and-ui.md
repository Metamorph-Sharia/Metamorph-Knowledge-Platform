# 05 Airflow stack: role by name, UI through CloudFront with a password

Status: resolved
Blocked by: 02

Spec: `../spec.md`, the decision "The Airflow stack", and user stories 9–10 and 22–26. Notes: see ticket 02.

## What to build
- **The Airflow stack template:**
  - remove its IAM role and take `AirflowTaskRole` (default `metamorph-airflow-task`) as a parameter;
  - the execution role from the core export;
  - `METAMORPH_TASK_LAUNCHER=ecs` and the `METAMORPH_ECS_*` settings, as before.
- **UI access:** copy the pattern of `deploy/aws/dev/retrieval.yaml`:
  - an internal ALB in front of the webserver;
  - a CloudFront VPC origin and distribution;
  - a CloudFront Function requiring HTTP Basic auth, which compares the sha256 of the password with a `PasswordSha256` stack parameter and on failure returns 401 with `WWW-Authenticate: Basic`;
  - an optional `WebAclArn` parameter.
- **The webserver's base URL** is the CloudFront address. Use a parameter if a circular dependency forces it.
- **A WAF script** for this distribution in the ingestion deploy directory, modeled on `deploy/aws/dev/waf.sh`.
- `tunnel.sh` is no longer the way in: remove it, or mark it optional.
- Tag everything `Owner=project3`.

Tests go in `tests/test_ingestion_stacks.py`:
- the Airflow template takes its task role from a parameter;
- the function's code checks the hash and asks for Basic auth;
- nothing in the template embeds a plain password.

## Acceptance
- The full test suite passes.
- `cfn-lint` is clean.

## Comments

2026-11-23: implemented on branch `ingestion-on-aws` (merge of `t05-*`); review fixes in the "Merge review fixes" commit.
