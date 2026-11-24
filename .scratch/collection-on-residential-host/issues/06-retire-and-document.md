# 06 Retire collection on AWS in the templates; narrow alerts; document both sides

Status: ready-for-agent
Blocked by: 03, 04, 05
Spec: ../spec.md ("AWS clean-up, only after the gate"; user story 46)

## What

Template and docs changes (deploying them waits for the cutover gate; that is a manual step, not this ticket):
- jobs stack: remove the nine connector task definitions, their `*_CONTACT` and connector-only parameters, the bi-stats inbox init container.
- shared stack: remove EFS, its access points and its security group rules, and the connector image repositories; keep what processing uses.
- alerts: the EventBridge rule's family list narrows to the processing families (platform, retrieval, ops); MinerU stays excluded.
- push-images.sh: drop the connector images from the ingestion list.
- deploy/aws/ingestion/README.md: the two sides; the cutover order (hand run per ingest DAG from the Mac inside the window → bundle loaded on AWS → health passes → first scheduled weekday → then deploy the retirement); the SSO re-login note; MinerU's hand start.
- check.sh: drop checks for retired pieces (EFS, connector task definitions); add the MinerU front door.

## Acceptance

- Template tests (tests/test_ingestion_stacks.py): the retired resources are absent; the alert rule lists only processing families.
- Full suite passes.
