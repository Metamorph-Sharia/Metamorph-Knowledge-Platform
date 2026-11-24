#!/bin/bash
# Builds Metamorph's images on this Mac (arm64, Fargate's Graviton) and pushes them to ECR in Jakarta, all with one
# tag (docs/aws-deployment-guide.md). MinerU's image is x86-64 and is built on the GPU instance instead (Phase 3).
#
#   deploy/aws/push-images.sh                          the core's images: platform, curation-web
#   deploy/aws/push-images.sh retrieval                Metamorph Retrieval, once deploy/aws/retrieval.yaml made its repository
#   deploy/aws/push-images.sh airflow                  Airflow's image, once the ingestion layer has its repository
#                                                      (the connectors' images are built on the collection host, never pushed)
#   TAG=20261024-1 deploy/aws/push-images.sh           a tag of your own (default: the UTC time)
#
# It builds the working trees as they are: commit first, so a tag always names code that is in git.
set -euo pipefail

platform="$(cd "$(dirname "$0")/../.." && pwd)"
workspace="$(dirname "$platform")"
region="${AWS_REGION:-ap-southeast-3}"
registry="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$region.amazonaws.com"
tag="${TAG:-$(date -u +%Y%m%d-%H%M)}"
CORE=(platform curation-web)
INGESTION=(airflow)
IMAGES=("${CORE[@]}" retrieval "${INGESTION[@]}")

build() {  # repository, build context, Dockerfile
  docker build --platform linux/arm64 -t "$registry/metamorph/$1:$tag" -f "$3" "$2"
  docker push "$registry/metamorph/$1:$tag"
}

[ $# -gt 0 ] || set -- "${CORE[@]}"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
for image in "$@"; do
  case "$image" in
    platform)          build platform "$platform" "$platform/docker/platform.Dockerfile" ;;
    curation-web)      build curation-web "$workspace/Metamorph-Curation-Web" "$workspace/Metamorph-Curation-Web/Dockerfile" ;;
    retrieval)         build retrieval "$workspace/Metamorph-Retrieval" "$workspace/Metamorph-Retrieval/Dockerfile" ;;
    airflow)           build airflow "$platform/dags" "$platform/docker/airflow.Dockerfile" ;;
    *) echo "unknown image: $image (one of: ${IMAGES[*]})" >&2; exit 2 ;;
  esac
done
echo "pushed with tag $tag"
