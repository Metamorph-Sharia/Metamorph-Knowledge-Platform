# 05 load_bundles: the processing side loads what collection uploaded

Status: ready-for-agent
Blocked by: 01, 02
Spec: ../spec.md ("Loading on the processing side")

## What

A processing-side DAG `load_bundles`, every 30 minutes, `catchup` off, one active run. One task per connector job, taken from the job registry, running ticket 02's `load-pending` for that connector's S3 prefix in the platform image (ECS launcher on AWS). Each task emits its layer's registry Dataset (`registry` or `market-registry`) when it ran, so registry_build and market_publish follow as today. One connector's held bundle fails only its own task. The platform's ECS task definition gets what it needs to read the ops bucket's bundles/ prefix (the bucket name setting; the platform task role already allows S3 per deploy/aws/iam/).

## Acceptance

- Plain-data tests (tests/test_dag_jobs.py): one load-pending task per connector job, its prefix, its layer, its Dataset; the DAG builds only on the processing side.
- Template tests if the jobs stack changes.
- Full suite passes.
