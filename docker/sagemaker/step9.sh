#!/bin/bash
# Step 9 on SageMaker AI (docs/aws-step9-sagemaker-guide.md). From the files docker/aws/stage-upload.sh made,
# MinerU is installed and started on this GPU, and every connector re-extracts the PDFs it already holds with it
# and exports its bundle. Nothing is fetched from the sources. SageMaker has no Docker, so everything runs
# natively: MinerU in its own virtualenv, each connector in its own uv environment. The same script runs in a
# Studio JupyterLab terminal and as a training job (train_entry.py).
#
#   INPUTS      the staged files: source.tgz, data-<repo>.tgz                      required
#   WORK        where the workspace is unpacked and the environments built     default ~/step9-work
#   CACHE       MinerU's readings, a folder per connector. A training job puts them in its checkpoint folder,
#               so a new job given the same folder resumes from them           default $WORK/mineru-cache
#   OUT         the results: <run>-bundles.tgz, <run>-mineru-cache.tgz        default $WORK/out
#   LOGS        the logs, each connector's and MinerU's                        default $OUT/logs
#   RUN_ID      the bundles' run id                                            default step9
#   MODE        run (default): the whole re-extraction; check: install, start and benchmark MinerU only
#   MINERU_URL  a MinerU already running, instead of installing one here
#   MINERU_CONCURRENCY  parse jobs at once                                     default 1
set -uo pipefail

: "${INPUTS:?set INPUTS to the folder holding source.tgz and the data-*.tgz files}"
WORK="${WORK:-$HOME/step9-work}"
CACHE="${CACHE:-$WORK/mineru-cache}"
OUT="${OUT:-$WORK/out}"
RUN_ID="${RUN_ID:-step9}"
MODE="${MODE:-run}"
MINERU_VERSION=4.0.12
CUDA_13_DRIVER=580  # the default build (vLLM 0.28, torch for CUDA 13.0) needs it; older drivers get CUDA 12.8
CONNECTORS="OJK-Source-Connector BPK-Source-Connector BI-Source-Connector DSN-MUI-Source-Connector"
export PATH="$HOME/.local/bin:$PATH"
# A training job's image points PYTHONPATH at its own Python 3.13, whose standard library then shadows the 3.12
# and 3.11 of MinerU and the connectors ("cannot import name 'NoDefault' from '_typing'"): each brings its own
unset PYTHONPATH PYTHONHOME
logs="${LOGS:-$OUT/logs}"
mkdir -p "$WORK" "$CACHE" "$OUT" "$logs"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$logs/step9.log"; }
fail() { log "FAILED: $*"; exit 1; }

unpack() {
  local quiet=()
  tar --version | grep -q GNU && quiet=(--warning=no-unknown-keyword)  # macOS's extended-attribute headers
  # an upload staged before stage-upload.sh left out macOS's metadata holds "._name" entries: the first may be one
  workspace="$WORK/$(tar "${quiet[@]+"${quiet[@]}"}" -tzf "$INPUTS/source.tgz" | cut -d/ -f1 | grep -v '^\._' | head -n 1)"
  [ -f "$WORK/.unpacked" ] && return
  log "unpacking the source and the connectors' data"
  if [ -f "$INPUTS/checksums.sha256" ]; then  # a browser upload that stopped short leaves a truncated file
    (cd "$INPUTS" && sha256sum --check --quiet checksums.sha256) \
      || fail "an input differs from the Mac's (above): upload it again"
  fi
  rm -f "$WORK"/._*
  tar "${quiet[@]+"${quiet[@]}"}" -xzf "$INPUTS/source.tgz" -C "$WORK" || fail "source.tgz"
  for repository in $CONNECTORS; do
    tar "${quiet[@]+"${quiet[@]}"}" -xzf "$INPUTS/data-$repository.tgz" -C "$workspace" || fail "data-$repository.tgz"
  done
  find "$WORK" -name '._*' -type f -delete  # Finder metadata, unpacked as files beside the real ones
  touch "$WORK/.unpacked"
}

install_uv() {
  command -v uv >/dev/null || python3 -m pip install --quiet --user uv || fail "installing uv"
}

install_mineru() {
  venv="$WORK/mineru-venv"
  export MINERU_HOME="$WORK/mineru-home" MINERU_MODEL_SOURCE=huggingface \
    MINERU_MODEL_SMALL_BACKEND=torch MINERU_MODEL_VLM_ENGINE=vllm
  if [ ! -x "$venv/bin/mineru-kit" ]; then
    driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)" || fail "no NVIDIA GPU"
    pins=()
    [ "${driver%%.*}" -ge "$CUDA_13_DRIVER" ] || pins=("vllm==0.19.1")  # torch 2.10 for CUDA 12.8
    log "installing MinerU $MINERU_VERSION for NVIDIA driver $driver ${pins[*]:-}"
    uv venv --quiet --python 3.12 "$venv" || fail "the MinerU virtualenv"
    uv pip install --quiet --python "$venv/bin/python" "mineru[full]==$MINERU_VERSION" ${pins[@]+"${pins[@]}"} \
      || fail "installing MinerU"
  fi
  command -v cc >/dev/null || command -v gcc >/dev/null || log "WARNING: no C compiler; vLLM's Triton needs one"
  "$venv/bin/mineru-kit" models verify --tier standard >/dev/null 2>&1 \
    || "$venv/bin/mineru-kit" models download --tier standard || fail "downloading MinerU's models"
}

start_mineru() {
  if [ -n "${MINERU_URL:-}" ]; then
    url="$MINERU_URL"
    return
  fi
  url=http://127.0.0.1:8010
  curl -sf "$url/v1/health" >/dev/null && { log "MinerU is up: $(curl -s "$url/v1/health")"; return; }
  # a server whose models failed to load keeps answering 503, and holds its upload directory: stop it first
  pkill -f "mineru-kit api-server" && sleep 5
  install_mineru
  log "starting MinerU"
  [ -f "$logs/mineru.log" ] && mv "$logs/mineru.log" "$logs/mineru.previous.log"
  # No image analysis, as everywhere: it writes descriptions of pictures as if they were the page's text. vLLM's
  # FlashInfer sampler compiles itself on first use, with build tools SageMaker's images lack: PyTorch's sampler
  # needs none (and docker/mineru/Dockerfile sets the same).
  VLLM_USE_FLASHINFER_SAMPLER=0 nohup "$venv/bin/mineru-kit" api-server --host 127.0.0.1 --port 8010 \
    --tier standard --preload-models --disable-image-analysis --upload-dir "$WORK/mineru-uploads" \
    --concurrency "${MINERU_CONCURRENCY:-1}" >"$logs/mineru.log" 2>&1 &
  local server=$!
  for _ in $(seq 1 240); do
    curl -sf "$url/v1/health" >/dev/null && { log "MinerU is up: $(curl -s "$url/v1/health")"; return; }
    kill -0 "$server" 2>/dev/null || fail "MinerU stopped: see $logs/mineru.log"
    if grep -q "Model initialization failed" "$logs/mineru.log"; then
      kill "$server"
      fail "MinerU couldn't load its models: see $logs/mineru.log"
    fi
    sleep 5
  done
  kill "$server"
  fail "MinerU didn't start in 20 minutes: see $logs/mineru.log"
}

prepare_connectors() {
  for repository in $CONNECTORS; do
    (cd "$workspace/$repository" && uv sync --quiet --frozen --no-dev) || fail "the environment of $repository"
    mkdir -p "$CACHE/$repository"
    rm -rf "$workspace/$repository/data/mineru-cache"
    ln -s "$CACHE/$repository" "$workspace/$repository/data/mineru-cache"
  done
}

reextract_command() {  # each connector's own offline re-extraction, then its export (dags/metamorph_pipeline/jobs.py)
  local out="$WORK/bundles/$1/$RUN_ID" uv="uv run --frozen --no-dev"
  case "$1" in
    ojk) echo "$uv ojk-connector reparse; rc=\$?; rm -rf $out; $uv ojk-connector export --format v2 --out $out --run-id $RUN_ID || exit 3; exit \$rc" ;;
    bpk) echo "$uv bpk-connector extract --again; rc=\$?; rm -rf $out; $uv bpk-connector export --format v2 --out $out --run-id $RUN_ID || exit 3; exit \$rc" ;;
    # BI's records only: its database's 62 PDFs are all in its records, so they are read here, and its database
    # is re-read on the Mac at rollout from the same readings. No Postgres is needed on SageMaker.
    bi-website) echo "$uv python -c 'from pathlib import Path; from src.pipeline.reextract import ReextractStats, reextract_records; s = ReextractStats(); reextract_records(Path(\"data/processed_json/BI\"), Path(\".\"), s); print(s)'; rc=\$?; rm -rf $out; $uv python -m src.pipeline.exporter_v2 --out $out --run-id $RUN_ID || exit 3; exit \$rc" ;;
    dsn-fatwa) echo "$uv python scripts/reextract.py; rc=\$?; rm -rf $out; $uv dsn export --out $out --run-id $RUN_ID || exit 3; exit \$rc" ;;
  esac
}

bundle_of() {
  case "$1" in
    OJK-Source-Connector) echo ojk ;;
    BPK-Source-Connector) echo bpk ;;
    BI-Source-Connector) echo bi-website ;;
    DSN-MUI-Source-Connector) echo dsn-fatwa ;;
  esac
}

reextract_all() {
  log "re-extracting with MinerU at $url; logs in $logs"
  local pids=() names=()
  for repository in $CONNECTORS; do
    bundle="$(bundle_of "$repository")"
    (
      cd "$workspace/$repository" || exit 2
      export METAMORPH_PDF_ENGINE=mineru METAMORPH_PDF_LINES=printed METAMORPH_MINERU_URL="$url" \
        METAMORPH_MINERU_CACHE=data/mineru-cache DATABASE_URL=postgresql+psycopg://unused@127.0.0.1:1/unused
      sh -c "$(reextract_command "$bundle")"
    ) >"$logs/$bundle.log" 2>&1 &
    pids+=($!)
    names+=("$bundle")
  done
  for index in "${!pids[@]}"; do
    wait "${pids[$index]}"
    log "${names[$index]}: exit $? (see $logs/${names[$index]}.log)"
  done
}

package() {
  log "packaging the results in $OUT"
  tar -czf "$OUT/$RUN_ID-bundles.tgz" -C "$WORK/bundles" . || fail "packaging the bundles"
  local caches=()
  for repository in $CONNECTORS; do caches+=("$repository/data/mineru-cache"); done
  # -h follows each data/mineru-cache link, so the archive unpacks into each connector's own cache on the Mac
  tar -czhf "$OUT/$RUN_ID-mineru-cache.tgz" -C "$workspace" "${caches[@]}" || fail "packaging the readings"
  cp -R "$logs" "$OUT/" 2>/dev/null || true  # the logs go with the results too
  ls -lh "$OUT" | tee -a "$logs/step9.log"
}

benchmark() {
  local raw="$workspace/BPK-Source-Connector/data/raw"
  (cd "$workspace/BPK-Source-Connector" && uv run --frozen --no-dev python -u \
    ../Metamorph-Knowledge-Platform/packages/metamorph-pdf-text/scripts/mineru_check.py --url "$url" \
    "$raw/79/79dd6317b3b0a647a61012a60ce574f98075577fc8f7a591108a4cc138ca95c0" \
    "$raw/a5/a50d9ee2f39bd2e59386e8b52dfc415b4bfaf425c75561bb1346dd29b9d37241") 2>&1 | tee -a "$logs/benchmark.log"
}

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | tee -a "$logs/step9.log"
unpack
install_uv
start_mineru
prepare_connectors
case "$MODE" in
  check) benchmark ;;
  run) reextract_all && package ;;
  *) fail "MODE must be run or check, not $MODE" ;;
esac
log "done"
