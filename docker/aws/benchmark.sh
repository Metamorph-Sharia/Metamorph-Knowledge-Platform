#!/bin/bash
# The go / no-go before the long run (docs/aws-step9-guide.md): mineru_check against this instance's MinerU, timing
# a 50-page BPK scan and a 43-page born-digital BPK regulation, the two files timed on the Mac in step 8.
# It runs from a connector image, which holds metamorph_pdf_text.   docker/aws/benchmark.sh [PDF ...]
set -euo pipefail

platform="$(cd "$(dirname "$0")/../.." && pwd)"
raw="$(dirname "$platform")/BPK-Source-Connector/data/raw"
pdfs=("$@")
if [ ${#pdfs[@]} -eq 0 ]; then
  pdfs=("$raw/79/79dd6317b3b0a647a61012a60ce574f98075577fc8f7a591108a4cc138ca95c0"
        "$raw/a5/a50d9ee2f39bd2e59386e8b52dfc415b4bfaf425c75561bb1346dd29b9d37241")
fi

mounts=()
inside=()
for index in "${!pdfs[@]}"; do
  mounts+=(-v "$(realpath "${pdfs[$index]}"):/pdfs/$index.pdf:ro")
  inside+=("/pdfs/$index.pdf")
done

docker run --rm --network metamorph \
  -e METAMORPH_MINERU_API_KEY="$(sed -n 's/^METAMORPH_MINERU_API_KEY=//p' "$platform/.env" | tail -n 1)" \
  -v "$platform/packages/metamorph-pdf-text/scripts:/check:ro" "${mounts[@]}" \
  metamorph/bpk-connector:dev python -u /check/mineru_check.py --url http://mineru:8010 "${inside[@]}"
