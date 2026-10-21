#!/bin/sh
# The MinerU service on this Mac, where Docker has no GPU: what dev.mineru.plist keeps running, and what can be
# run by hand. Installed with `uv tool install --python 3.12 "mineru[torch]==4.0.12"` (README: Running MinerU).
# Its API key, if any, is METAMORPH_MINERU_API_KEY in the platform's .env, which the connectors are given too.
set -eu

platform="$(cd "$(dirname "$0")/../.." && pwd)"
key="$(sed -n 's/^METAMORPH_MINERU_API_KEY=//p' "$platform/.env" 2>/dev/null | tail -n 1)"

# --tier standard serves basic too; one job at a time fits 24 GB; models load before /v1/health says ok.
set -- api-server --host 127.0.0.1 --port "${METAMORPH_MINERU_PORT:-8010}" --tier standard --concurrency 1 \
  --preload-models
if [ -n "$key" ]; then
  set -- "$@" --api-key "$key"
fi
exec "$HOME/.local/bin/mineru-kit" "$@"
