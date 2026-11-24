#!/bin/bash
# A rate limit in front of one of the ingestion layer's CloudFront addresses: Airflow's UI (airflow.yaml) or MinerU's
# front door (mineru.yaml). A web ACL for CloudFront lives in us-east-1, where the organization's policy denies
# CloudFormation, so this script makes it with the WAF CLI instead (the pattern of deploy/aws/dev/waf.sh). It bounds
# what one address can ask for: a password-guessing loop at the UI, a key-guessing loop at MinerU. The UI's password
# is checked at the edge, MinerU's key by MinerU itself.
#
#   deploy/aws/ingestion/waf.sh create [airflow|mineru]    prints the web ACL's ARN, for that stack's WebAclArn
#   deploy/aws/ingestion/waf.sh delete [airflow|mineru]    after that stack no longer names it
#
# The target is airflow when none is named.
set -euo pipefail

waf() { aws wafv2 --region us-east-1 "$@"; }
visibility() { echo "SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=$1"; }
usage() { echo "usage: $0 create|delete [airflow|mineru]" >&2; exit 2; }

# Per IP address, then blocked until its rate falls. MinerU's jobs poll every 5 s and several run at once from the
# one home address, and the key is a bearer secret: its limit is higher.
case "${2:-airflow}" in
  airflow) NAME=metamorph-airflow; REQUESTS_PER_FIVE_MINUTES=300 ;;
  mineru)  NAME=metamorph-mineru;  REQUESTS_PER_FIVE_MINUTES=2000 ;;
  *) usage ;;
esac

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
  *) usage ;;
esac
