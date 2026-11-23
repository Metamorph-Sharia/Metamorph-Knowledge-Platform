# 03 Jobs stack: nine connectors, platform, ops; roles by name

Status: ready-for-agent
Blocked by: 01, 02

Spec: `../spec.md`, the decisions "The jobs stack" and "Roles come in as names". Notes: see ticket 02.

## What to build
Rework the jobs stack template:
- One task definition for every image any DAG runs (connectors, platform, ops), with family `task_family(image)`. Retrieval's refresh already exists in the retrieval stack, so don't duplicate it; check which families already exist live (see the notes).
- **Parameters:**
  - role names `ConnectorTaskRole` (default `metamorph-connector-task`) and `PlatformTaskRole` (default `metamorph-platform-task`);
  - the execution role from the core's `metamorph-execution-role` export;
  - the ops task runs as the connector role.
- **Mounts:** each connector task definition mounts only its own access point plus bundles. The platform mounts bundles, read-only.
- The BI statistics task keeps its `amazon/aws-cli` init container, which copies `inbox/bi-seki/` from the ops bucket into the connector's inbox.
- Sizes: connectors 0.5–1 vCPU and 2 GB, platform 1 vCPU and 4 GB. Nothing above 2 vCPU or 8 GB.
- Tag everything `Owner=project3`. Remove all IAM resources.

Tests go in `tests/test_ingestion_stacks.py`, beside 02's:
- every DAG image has its task definition;
- each connector mounts its own access point and no other connector's;
- the task roles come from parameters.

## Acceptance
- The full test suite passes.
- `cfn-lint` is clean.
