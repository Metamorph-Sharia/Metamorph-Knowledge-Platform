#!/bin/bash
# Prepares the AWS instance for step 9 from what stage-upload.sh put in the bucket (docs/aws-step9-guide.md):
# each connector's data, a .env with a new MinerU API key, the idle guard, the images, the compose stack and BI's
# database. Run as ubuntu from the unpacked source; running it again skips what is already done.
#   BUCKET=metamorph-step9-123456789012 docker/aws/instance-setup.sh
set -euo pipefail
: "${BUCKET:?set BUCKET to the step 9 bucket}"

platform="$(cd "$(dirname "$0")/../.." && pwd)"
workspace="$(dirname "$platform")"
CONNECTORS="BI-Source-Connector BPK-Source-Connector OJK-Source-Connector DSN-MUI-Source-Connector"
compose() { docker compose --project-directory "$platform" "$@"; }

if ! nvidia-smi --query-gpu=name,driver_version --format=csv,noheader; then
  echo "No NVIDIA driver: this is not the Deep Learning AMI. See the guide's fallback for plain Ubuntu." >&2
  exit 1
fi
docker compose version >/dev/null 2>&1 || sudo apt-get install -y docker-compose-plugin

for repository in $CONNECTORS; do
  if [ ! -f "$workspace/$repository/data/.staged" ]; then
    echo "data of $repository"
    aws s3 cp --only-show-errors "s3://$BUCKET/inputs/data-$repository.tgz" - | tar -xzf - -C "$workspace"
    touch "$workspace/$repository/data/.staged"
  fi
done

if [ ! -f "$platform/.env" ]; then
  cp "$platform/.env.example" "$platform/.env"
  printf 'METAMORPH_PDF_ENGINE=mineru\nMETAMORPH_MINERU_API_KEY=%s\n' "$(openssl rand -hex 24)" >>"$platform/.env"
fi

echo "*/15 * * * * $platform/docker/aws/idle-stop.sh" | sudo crontab -  # stops the instance after an idle hour

echo "building the images: 30-60 minutes the first time"
compose --profile mineru build mineru
compose --profile connectors build ojk-connector bpk-connector dsn-mui-connector bi-connector
compose build migrate

compose up -d --wait postgres objectstore
compose up -d migrate
tables="$(compose exec -T postgres psql -U metamorph -d bi -Atc "select count(*) from information_schema.tables where table_schema = 'public'")"
if [ "$tables" = 0 ]; then
  aws s3 cp --only-show-errors "s3://$BUCKET/inputs/bi.dump" - | compose exec -T postgres pg_restore -U metamorph -d bi --no-owner --role=bi
fi

echo "starting MinerU: healthy once its models are loaded"
compose --profile mineru up -d --wait --wait-timeout 1200 mineru
compose --profile mineru ps
echo "Ready. Next: docker/aws/benchmark.sh"
