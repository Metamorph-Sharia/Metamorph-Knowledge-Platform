#!/bin/bash
# Starts step 9's run (reextract-all.sh) in a detached tmux session named step9, and makes it resume whenever the
# instance boots with the run unfinished, as it does after a Spot interruption (docs/aws-step9-guide.md).
#   BUCKET=metamorph-step9-123456789012 docker/aws/start-run.sh     the first run (RUN_ID=step9-2 for a rerun)
#   docker/aws/start-run.sh                                          at boot, from cron: the run still pending
# Watch it with `tmux attach -t step9` (detach: Ctrl-b d) or `tail -f ~/work/step9.out`.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin  # cron's PATH is shorter

platform="$(cd "$(dirname "$0")/../.." && pwd)"
pending="$HOME/work/step9.pending"  # the BUCKET and RUN_ID of a run that hasn't finished
output="$HOME/work/step9.out"
mkdir -p "$HOME/work"

if [ "${1:-}" = --run ]; then  # inside the tmux session
  . "$pending"
  export BUCKET RUN_ID
  cd "$platform"
  docker compose up -d --wait postgres objectstore
  if docker/aws/reextract-all.sh 2>&1 | tee -a "$output"; then
    rm -f "$pending"  # finished: a later boot doesn't start it again
  fi
  exit 0
fi

if [ -n "${BUCKET:-}" ]; then
  printf 'BUCKET=%s\nRUN_ID=%s\n' "$BUCKET" "${RUN_ID:-step9}" >"$pending"
fi
if [ ! -f "$pending" ]; then
  echo "No run pending. Start one with BUCKET=... $0"
  exit 0
fi

resume="@reboot sleep 90; $platform/docker/aws/start-run.sh >>$output 2>&1"
{ crontab -l 2>/dev/null | grep -vF "docker/aws/start-run.sh" || true; echo "$resume"; } | crontab -

if tmux has-session -t step9 2>/dev/null; then
  echo "Already running: tmux attach -t step9"
else
  tmux new-session -d -s step9 "$0 --run"
  echo "Started: tmux attach -t step9, or tail -f $output"
fi
