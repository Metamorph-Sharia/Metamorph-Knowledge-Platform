#!/bin/sh
# Stops this instance after an hour with nothing to do, so a finished or stuck run stops billing. It runs from
# root's crontab every 15 minutes (docs/aws-step9-guide.md, Phase 3). Idle is a 15-minute load average under 0.2;
# four checks in a row stop it. It works on Spot and on demand alike, where a CloudWatch stop action may not.
checks=/tmp/idle-checks  # cleared at boot, so a restarted instance starts counting again
if awk '{ exit !($3 < 0.2) }' /proc/loadavg; then
  count=$(( $(cat "$checks" 2>/dev/null || echo 0) + 1 ))
else
  count=0
fi
echo "$count" >"$checks"
if [ "$count" -ge 4 ]; then
  shutdown -h now "idle-stop: idle for an hour"
fi
