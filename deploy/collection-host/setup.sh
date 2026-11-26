#!/bin/bash
# Sets up or restarts the collection host: the machine that runs the connectors from an Indonesian internet line that
# is not a cloud address (docs/adr/0001-collection-on-a-residential-host.md). Run it from anywhere:
#
#   deploy/collection-host/setup.sh            check the settings and AWS sign-in, build the images, start Airflow
#   deploy/collection-host/setup.sh --check    only the checks
#
# Compose runs this Airflow as the collection side (METAMORPH_SIDE=collection is set in compose.yaml). The settings it
# needs are in .env; .env.example explains each one, and deploy/aws/ingestion/README.md ("The collection host") the rest.
# Not yet tested as a script: it wraps the steps the reference deployment ran by hand.
set -euo pipefail

cd "$(dirname "$0")/../.."
fail() { echo "setup: $*" >&2; exit 1; }
warn() { echo "setup: warning: $*" >&2; }

[ -f .env ] || fail "no .env: copy .env.example to .env and fill it in"
set -a; source .env; set +a

[ -n "${METAMORPH_WORKSPACE:-}" ] && [ -d "$METAMORPH_WORKSPACE" ] || fail "METAMORPH_WORKSPACE must be the folder holding every repository"
for repo in OJK-Source-Connector BI-Source-Connector BPK-Source-Connector DSN-MUI-Source-Connector OJK-Register-Connector \
            OJK-Stats-Connector BI-Stats-Connector BPS-Stats-Connector Reports-Connector; do
  [ -d "$METAMORPH_WORKSPACE/$repo" ] || fail "missing $METAMORPH_WORKSPACE/$repo: clone every connector next to the platform"
done
for name in METAMORPH_BUNDLES_BUCKET METAMORPH_OPS_BUCKET; do
  value="${!name:-}"
  [ -n "$value" ] && [[ "$value" != *"<"* ]] || fail "set $name in .env"
done

profile=(); [ -n "${METAMORPH_AWS_PROFILE:-}" ] && profile=(--profile "$METAMORPH_AWS_PROFILE")
aws sts get-caller-identity "${profile[@]}" >/dev/null 2>&1 \
  || fail "AWS credentials are missing or expired: run aws sso login ${profile[*]} (or renew the host's own credentials)"
aws s3 ls "s3://$METAMORPH_BUNDLES_BUCKET/" "${profile[@]}" >/dev/null 2>&1 || fail "cannot list s3://$METAMORPH_BUNDLES_BUCKET"

if [ "${METAMORPH_PDF_ENGINE:-}" = mineru ]; then
  [ -n "${METAMORPH_MINERU_URL:-}" ] && [ -n "${METAMORPH_MINERU_API_KEY:-}" ] \
    || fail "METAMORPH_PDF_ENGINE=mineru needs METAMORPH_MINERU_URL (the mineru stack's FrontDoorUrl) and METAMORPH_MINERU_API_KEY"
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$METAMORPH_MINERU_URL" || true)
  [ "$code" != 000 ] || warn "MinerU's front door does not answer; that is normal outside its window"
else
  warn "METAMORPH_PDF_ENGINE is not mineru: scanned PDFs will not be read with OCR"
fi

echo "setup: checks passed"
[ "${1:-}" = --check ] && exit 0

docker compose --profile connectors build
docker compose up -d
echo "setup: Airflow (collection side) at http://localhost:8080. Every DAG starts paused: unpause an ingest_* DAG to enable its source."
