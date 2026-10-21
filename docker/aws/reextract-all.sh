#!/bin/bash
# Every connector re-extracts the PDFs it already holds with MinerU (no network fetch), exports a contract v2
# bundle, and the bundles are loaded and built into this compose stack's database (docs/aws-step9-guide.md).
#
#   On the AWS instance (step 9):  BUCKET=metamorph-step9-123456789012 docker/aws/reextract-all.sh
#   On the Mac (the live rollout): MINERU_URL=http://host.docker.internal:8011 docker/aws/reextract-all.sh
#
# BUCKET, when set, receives MinerU's readings every SYNC_SECONDS while the run goes on; at the end, a dump of the
# database and the readings and logs as one .tgz each (out/<run>-…). The instance then stops itself unless
# STOP_WHEN_DONE=0. A run stopped half way resumes from the readings in each connector's data/mineru-cache: run the
# script again (docker/aws/start-run.sh does that at boot).
set -uo pipefail

platform="$(cd "$(dirname "$0")/../.." && pwd)"
workspace="$(dirname "$platform")"
run_id="${RUN_ID:-step9}"
mineru_url="${MINERU_URL:-http://mineru:8010}"
logs="$workspace/reextract-logs/$run_id"
mkdir -p "$logs"
setting() {  # one value from the platform's .env. Sourcing it whole would export its AWS_* keys, which are the
  # local object store's, and the aws CLI would use them instead of the instance's role.
  sed -n "s/^$1=\([^ #]*\).*/\1/p" "$platform/.env" | tail -n 1
}
METAMORPH_MINERU_API_KEY="$(setting METAMORPH_MINERU_API_KEY)"
BI_DB_PASSWORD="$(setting BI_DB_PASSWORD)"

#            repository                image                             bundle      fails from
CONNECTORS=("OJK-Source-Connector      metamorph/ojk-connector:dev       ojk         2"
            "BPK-Source-Connector      metamorph/bpk-connector:dev       bpk         2"
            "BI-Source-Connector       metamorph/bi-connector:dev        bi-website  1"
            "DSN-MUI-Source-Connector  metamorph/dsn-mui-connector:dev   dsn-fatwa   2")

reextract_command() {  # the connector's own offline re-extraction, then its export (as dags/metamorph_pipeline/jobs.py)
  local out="/bundles/$1/$run_id"
  case "$1" in
    ojk) echo "ojk-connector reparse; rc=\$?; rm -rf $out; ojk-connector export --format v2 --out $out --run-id $run_id || exit 3; exit \$rc" ;;
    bpk) echo "bpk-connector extract --again; rc=\$?; rm -rf $out; bpk-connector export --format v2 --out $out --run-id $run_id || exit 3; exit \$rc" ;;
    bi-website) echo "python -m src.cli reextract; rc=\$?; rm -rf $out; python -m src.pipeline.exporter_v2 --out $out --run-id $run_id || exit 3; exit \$rc" ;;
    dsn-fatwa) echo "python scripts/reextract.py; rc=\$?; rm -rf $out; dsn export --out $out --run-id $run_id || exit 3; exit \$rc" ;;
  esac
}

run_connector() {
  local repository=$1 image=$2 bundle=$3
  docker run --rm --name "reextract-$bundle" --network metamorph \
    -v "$workspace/$repository/data:/workspace/$repository/data" -v metamorph-bundles:/bundles \
    -e METAMORPH_PDF_ENGINE=mineru -e METAMORPH_PDF_LINES="${METAMORPH_PDF_LINES:-printed}" \
    -e METAMORPH_MINERU_URL="$mineru_url" -e METAMORPH_MINERU_API_KEY="${METAMORPH_MINERU_API_KEY:-}" \
    -e METAMORPH_MINERU_CACHE=data/mineru-cache \
    -e DATABASE_URL="postgresql+psycopg://bi:${BI_DB_PASSWORD:-bi-dev}@postgres:5432/bi" \
    "$image" sh -c "$(reextract_command "$bundle")" >"$logs/$bundle.log" 2>&1
}

sync_readings() {
  [ -n "${BUCKET:-}" ] || return 0
  for line in "${CONNECTORS[@]}"; do
    read -r repository _ <<<"$line"
    cache="$workspace/$repository/data/mineru-cache"
    [ -d "$cache" ] && aws s3 sync --only-show-errors "$cache" "s3://$BUCKET/out/mineru-cache/$repository/"
  done
}

platform_cli() {
  docker compose --project-directory "$platform" run --rm -T -v metamorph-bundles:/bundles api "$@"
}

if [ -n "${BUCKET:-}" ]; then
  (while sleep "${SYNC_SECONDS:-600}"; do sync_readings; done) &
  syncer=$!
  trap 'kill "$syncer" 2>/dev/null' EXIT
fi

echo "$(date -u +%FT%TZ) re-extracting with MinerU at $mineru_url; logs in $logs"
pids=()  # in CONNECTORS' order (bash 3.2, macOS's, has no associative arrays)
for line in "${CONNECTORS[@]}"; do
  read -r repository image bundle _ <<<"$line"
  run_connector "$repository" "$image" "$bundle" &
  pids+=($!)
done

loadable=()
for index in "${!CONNECTORS[@]}"; do
  read -r _ _ bundle fails_from <<<"${CONNECTORS[$index]}"
  wait "${pids[$index]}"
  rc=$?
  echo "$(date -u +%FT%TZ) $bundle: exit $rc (see $logs/$bundle.log)"
  [ "$rc" -lt "$fails_from" ] && loadable+=("$bundle")
done
sync_readings

platform_cli storage init
for bundle in ${loadable[@]+"${loadable[@]}"}; do
  platform_cli load "/bundles/$bundle/$run_id" >>"$logs/load.log" 2>&1 || echo "load of $bundle failed: $logs/load.log"
done
platform_cli build >"$logs/build.log" 2>&1 || echo "build failed: $logs/build.log"
platform_cli health >"$logs/health.log" 2>&1
echo "$(date -u +%FT%TZ) loaded: ${loadable[*]+${loadable[*]}} (of ${#CONNECTORS[@]} connectors)"

if [ -n "${BUCKET:-}" ]; then
  docker compose --project-directory "$platform" exec -T postgres pg_dump -U metamorph -Fc metamorph \
    | aws s3 cp - "s3://$BUCKET/out/$run_id-database.dump"
  aws s3 sync --only-show-errors "$logs" "s3://$BUCKET/out/logs/$run_id/"
  # The same readings and logs as one file each, which the S3 console can download (it can't download a folder).
  caches=()
  for line in "${CONNECTORS[@]}"; do
    read -r repository _ <<<"$line"
    [ -d "$workspace/$repository/data/mineru-cache" ] && caches+=("$repository/data/mineru-cache")
  done
  [ ${#caches[@]} -gt 0 ] && tar -czf - -C "$workspace" "${caches[@]}" | aws s3 cp - "s3://$BUCKET/out/$run_id-mineru-cache.tgz"
  tar -czf - -C "$logs" . | aws s3 cp - "s3://$BUCKET/out/$run_id-logs.tgz"
  if [ "${STOP_WHEN_DONE:-1}" = 1 ]; then
    sudo shutdown -h +5 "reextract-all: done, stopping the instance"  # its EBS volume and data stay
  fi
fi
