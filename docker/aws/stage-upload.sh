#!/bin/bash
# Puts what step 9 on AWS needs in one folder, ready to upload to the bucket's inputs/ (docs/aws-step9-guide.md):
#   source.tgz              the workspace's repositories as they are, uncommitted work included; no data/, .env,
#                           virtualenvs, node_modules, EDA folder, backups/ or blobs/
#   source-revisions.txt    each repository's commit, and how many files differ from it
#   data-<repo>.tgz         each connector's data/, without its old bundles (exports/) or MinerU readings
#   bi.dump                 BI's own database, which its reextract also updates
#   sagemaker-code.tar.gz   the SageMaker training job's entry point, runner and launcher (docker/sagemaker/)
#   checksums.sha256        the inputs' SHA-256 sums: step9.sh checks them, since a browser upload can stop short
# Nothing is fetched from the sources. Run on the Mac, with the compose stack up:
#   docker/aws/stage-upload.sh [OUT_DIR]        (default: ~/metamorph-step9-upload)
set -euo pipefail

platform="$(cd "$(dirname "$0")/../.." && pwd)"
workspace="$(dirname "$platform")"
name="$(basename "$workspace")"
out="${1:-$HOME/metamorph-step9-upload}"
CONNECTORS="BI-Source-Connector BPK-Source-Connector OJK-Source-Connector DSN-MUI-Source-Connector"
mkdir -p "$out"

# macOS's tar adds each file's Finder metadata as a hidden "._name" entry, which Linux's tar unpacks as a file
# (and lists first: "._Metamorph-Sharia"), and its extended attributes as headers Linux's tar warns about. Leave both out.
export COPYFILE_DISABLE=1
pack() { tar --no-xattrs --no-mac-metadata --exclude='.DS_Store' "$@"; }

echo "source.tgz"
pack -czf "$out/source.tgz" -C "$(dirname "$workspace")" \
  --exclude="$name/*/data" --exclude="$name/Metamorph-EDA" --exclude="$name/backups" --exclude="$name/blobs" --exclude='.venv' --exclude='node_modules' \
  --exclude='.next' --exclude='.env' --exclude='__pycache__' "$name"

cd "$workspace"
for repository in */; do
  [ -d "$repository/.git" ] || continue
  echo "${repository%/} $(git -C "$repository" rev-parse HEAD) dirty=$(git -C "$repository" status --short | wc -l | tr -d ' ')"
done >"$out/source-revisions.txt"

for repository in $CONNECTORS; do
  echo "data-$repository.tgz"
  pack -czf "$out/data-$repository.tgz" \
    --exclude="$repository/data/exports" --exclude="$repository/data/mineru-cache*" "$repository/data"
done

echo "sagemaker-code.tar.gz"
pack -czf "$out/sagemaker-code.tar.gz" -C "$platform/docker/sagemaker" train_entry.py step9.sh launch_job.py

echo "bi.dump"
docker compose --project-directory "$platform" exec -T postgres pg_dump -U metamorph -Fc bi >"$out/bi.dump"

(cd "$out" && shasum -a 256 source.tgz source-revisions.txt data-*.tgz bi.dump >checksums.sha256)

ls -lh "$out"
echo "Upload every file above to s3://<bucket>/inputs/"
