# 03 MinerU's front door: CloudFront to the internal load balancer

Status: ready-for-agent
Blocked by: none
Spec: ../spec.md ("MinerU" → the front door)

## What

In the mineru stack: a CloudFront distribution with a VPC origin on MinerU's existing internal load balancer, HTTPS for viewers, no caching, all methods, forwarding the Authorization header MinerU's API key travels in. No edge password: MinerU checks its own key. A WAF rate limit attached by script, as `deploy/aws/ingestion/waf.sh` does for Airflow (reuse or generalise it; don't copy-paste). Output the CloudFront address. Follow the Airflow stack's CloudFront + VPC origin as prior art. Tag Owner=project3 on everything; no IAM resources.

## Acceptance

- Template tests (prior art: tests/test_ingestion_stacks.py, the Airflow CloudFront tests): VPC origin on the internal balancer; HTTPS redirect; caching disabled; the key's header reaches the origin; the address is an output.
- Full suite passes.
