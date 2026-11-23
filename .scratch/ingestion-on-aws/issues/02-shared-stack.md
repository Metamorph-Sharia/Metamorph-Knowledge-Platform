# 02 Shared ingestion stack: no IAM, nine access points, no Cloud Map

Status: resolved
Blocked by: none

Spec: `../spec.md`, the decisions "Roles come in as names" and "The shared ingestion stack". Notes: `/private/tmp/claude-501/-Users-biru-Work-Metamorph-Sharia/a4b9134c-ad85-4425-806e-c4d22bfe291f/scratchpad/ingestion-notes.md`.

## What to build
Rework the shared ingestion stack template:
- **Remove** every `AWS::IAM::*` resource and the Cloud Map namespace.
- **EFS:**
  - tag the file system `Owner=project3` and `Project=metamorph` on create;
  - one access point per connector, nine in all; the connectors are the `connector` values in the DAG jobs;
  - one access point for bundles;
  - keep the OJK credentials access point only if the OJK connector's code still reads credentials; check its repository.
- ECR repositories for every connector image, Airflow and MinerU, with scan on push, immutable tags and a keep-last-10 lifecycle.
- Security groups as before, minus anything that only served Cloud Map.
- Every resource that takes tags gets `Owner=project3`.
- **Import only the live core's exports** (listed in the notes). Fix any import of `metamorph-exec-policy` or `metamorph-platform-role`.

Tests go in a new file, `tests/test_ingestion_stacks.py`, beside the deploy-layer test:
- no ingestion template declares an `AWS::IAM::*` resource. This test covers every ingestion template, so it will fail until 03–05 land. Mark it `xfail(strict=False)` with a note; ticket 07 removes the mark.
- a list of the live core's exports, kept beside the test, and a check that every import in shared resolves against it or against the ingestion exports;
- every connector job has an access point.

Run `cfn-lint` on the template if it is installed (`uvx cfn-lint`).

## Acceptance
- The full test suite passes.
- `cfn-lint` is clean.

## Comments

2026-11-23: implemented on branch `ingestion-on-aws` (merge of `t02-*`); review fixes in the "Merge review fixes" commit.
