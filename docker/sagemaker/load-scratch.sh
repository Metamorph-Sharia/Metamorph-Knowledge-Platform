#!/bin/bash
# Loads step 9's bundles from SageMaker into a scratch database beside the live one, metamorph_step9 with its
# own blob bucket, and builds it with parser 6: the "after" side of the step 9 comparison. The live database is
# not touched. Run on the Mac from the platform repository, with the compose stack up:
#   docker/sagemaker/load-scratch.sh ~/Downloads/step9-bundles.tgz [RUN_ID]
set -euo pipefail

bundles_tgz="${1:?the <run>-bundles.tgz from SageMaker}"
run_id="${2:-step9}"
platform="$(cd "$(dirname "$0")/../.." && pwd)"
database=metamorph_step9
unpacked="$(mktemp -d)"
trap 'rm -rf "$unpacked"' EXIT

setting() { sed -n "s/^$1=\\([^ #]*\\).*/\\1/p" "$platform/.env" | tail -n 1; }
user="$(setting POSTGRES_USER)"; user="${user:-metamorph}"
password="$(setting POSTGRES_PASSWORD)"; password="${password:-metamorph-dev}"
port="$(setting POSTGRES_PORT)"; port="${port:-5433}"
export METAMORPH_DATABASE_URL="postgresql://$user:$password@localhost:$port/$database"
export METAMORPH_S3_BUCKET=metamorph-step9-blobs

cd "$platform"
docker compose exec -T postgres createdb -U "$user" "$database" 2>/dev/null || echo "$database exists: loading into it"
tar -xzf "$bundles_tgz" -C "$unpacked"
cli() { uv run --env-file .env metamorph "$@"; }  # .env for the object store's keys; the two above win
seen="$(uv run --env-file .env python -c 'import os; print(os.environ["METAMORPH_DATABASE_URL"])')"
[ "$seen" = "$METAMORPH_DATABASE_URL" ] || { echo "refusing: the CLI would use $seen, not $database" >&2; exit 1; }
cli db migrate
cli storage init
for bundle in "$unpacked"/*/"$run_id"; do
  echo "loading $bundle"
  cli load "$bundle"
done
cli build
cli health || true
echo "Built $database. Compare it with the live database: the plan's Validation section."
