#!/bin/bash
# DEVELOPMENT ONLY: a rate limit in front of the retrieval gateway's development address (dev/retrieval.yaml). A web
# ACL for CloudFront lives in us-east-1, where the organization's policy denies CloudFormation, so this script makes
# it with the WAF CLI instead. It bounds what one address can ask of the 2-vCPU gateway, a runaway agent loop
# included; the token itself is checked at the edge.
#
#   deploy/aws/dev/waf.sh create    prints the web ACL's ARN, for dev/retrieval.yaml's WebAclArn
#   deploy/aws/dev/waf.sh delete    after dev/retrieval.yaml no longer names it
set -euo pipefail

NAME=metamorph-retrieval-dev
REQUESTS_PER_FIVE_MINUTES=1000   # per IP address, then blocked until its rate falls
waf() { aws wafv2 --region us-east-1 "$@"; }
visibility() { echo "SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=$1"; }

case "${1:-}" in
  create)
    rules=$(printf '[{"Name":"rate-per-address","Priority":0,"Action":{"Block":{}},"Statement":{"RateBasedStatement":{"Limit":%d,"AggregateKeyType":"IP","EvaluationWindowSec":300}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"rate-per-address"}}]' \
              "$REQUESTS_PER_FIVE_MINUTES")
    waf create-web-acl --name "$NAME" --scope CLOUDFRONT --default-action Allow={} --rules "$rules" \
      --visibility-config "$(visibility "$NAME")" --tags Key=Owner,Value=project3 --query Summary.ARN --output text ;;
  delete)
    read -r id token < <(waf list-web-acls --scope CLOUDFRONT \
      --query "WebACLs[?Name=='$NAME'] | [0].[Id, LockToken]" --output text)
    waf delete-web-acl --name "$NAME" --scope CLOUDFRONT --id "$id" --lock-token "$token" ;;
  *) echo "usage: $0 create|delete" >&2; exit 2 ;;
esac
