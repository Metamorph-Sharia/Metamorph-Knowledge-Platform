#!/bin/bash
# Puts what step 9 on AWS needs in one folder, ready to upload to the bucket's inputs/ (docs/aws-step9-guide.md):
#   source.tgz              the workspace's repositories as they are, uncommitted work included; no data/, .env,
#                           virtualenvs, node_modules or EDA folder
#   source-revisions.txt    each repository's commit, and how many files differ from it
#   data-<repo>.tgz         each connector's data/, without its old bundles (exports/) or MinerU readings
#   bi.dump                 BI's own database, which its reextract also updates
# Nothing is fetched from the sources. Run on the Mac, with the compose stack up:
#   docker/aws/stage-upload.sh [OUT_DIR]        (default: ~/metamorph-step9-upload)
set -euo pipefail

platform="$(cd "$(dirname "$0")/../.." && pwd)"
workspace="$(dirname "$platform")"
name="$(basename "$workspace")"
out="${1:-$HOME/metamorph-step9-upload}"
CONNECTORS="BI-Source-Connector BPK-Source-Connector OJK-Source-Connector DSN-MUI-Source-Connector"
mkdir -p "$out"

echo "source.tgz"
tar -czf "$out/source.tgz" -C "$(dirname "$workspace")" \
  --exclude="$name/*/data" --exclude="$name/Metamorph-EDA" --exclude='.venv' --exclude='node_modules' \
  --exclude='.next' --exclude='.env' --exclude='__pycache__' "$name"

cd "$workspace"
for repository in */; do
  [ -d "$repository/.git" ] || continue
  echo "${repository%/} $(git -C "$repository" rev-parse HEAD) dirty=$(git -C "$repository" status --short | wc -l | tr -d ' ')"
done >"$out/source-revisions.txt"

for repository in $CONNECTORS; do
  echo "data-$repository.tgz"
  tar -czf "$out/data-$repository.tgz" \
    --exclude="$repository/data/exports" --exclude="$repository/data/mineru-cache" "$repository/data"
done

echo "bi.dump"
docker compose --project-directory "$platform" exec -T postgres pg_dump -U metamorph -Fc bi >"$out/bi.dump"

ls -lh "$out"
echo "Upload every file above to s3://<bucket>/inputs/"
