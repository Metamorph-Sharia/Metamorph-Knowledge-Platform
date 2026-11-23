#!/bin/bash
# After a deploy: is the ingestion layer in the state README.md describes? Read-only (describe, get and list calls
# only), so it is safe to run at any time. Prints pass or FAIL per check and exits 1 if any failed.
#
#   deploy/aws/ingestion/check.sh
#
# It looks at:
#   - the five roles DevOps made and the instance profile, each trusted by the right service;
#   - the five ingestion stacks, complete;
#   - EFS, with its ten access points (nine connectors and the bundles);
#   - the MinerU instance, stopped outside the window the mineru stack was deployed with;
#   - the Airflow service, with a running task.
# A check whose stack is missing is skipped (the stack's own check has already failed).
set -uo pipefail

export AWS_DEFAULT_REGION="${AWS_REGION:-ap-southeast-3}"
CLUSTER=metamorph
ACCESS_POINTS=10   # one per connector (nine) and one for the bundles: shared.yaml
failures=0

pass() { printf 'pass  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
skip() { printf 'skip  %s\n' "$1"; }
first_line() { head -n 1 | cut -c 1-160; }

# --- roles: they exist and the right service may assume them --------------------------------------------------------

role() {   # role name, the service that must be trusted
  local trusted
  if ! trusted=$(aws iam get-role --role-name "$1" \
        --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output text 2>&1); then
    fail "role $1: $(first_line <<<"$trusted")"
  elif [[ " ${trusted//$'\t'/ } " == *" $2 "* ]]; then
    pass "role $1 trusts $2"
  else
    fail "role $1 trusts '$trusted', not $2"
  fi
}

role metamorph-airflow-task ecs-tasks.amazonaws.com
role metamorph-connector-task ecs-tasks.amazonaws.com
role metamorph-platform-task ecs-tasks.amazonaws.com
role metamorph-scheduler scheduler.amazonaws.com
role metamorph-mineru-instance ec2.amazonaws.com
if profile=$(aws iam get-instance-profile --instance-profile-name metamorph-mineru-instance \
      --query 'InstanceProfile.Roles[].RoleName' --output text 2>&1); then
  if [ "$profile" = metamorph-mineru-instance ]; then
    pass "instance profile metamorph-mineru-instance holds the role of that name"
  else
    fail "instance profile metamorph-mineru-instance holds '$profile'"
  fi
else
  fail "instance profile metamorph-mineru-instance: $(first_line <<<"$profile")"
fi

# --- stacks ---------------------------------------------------------------------------------------------------------

deployed=" "   # the complete stacks (bash 3.2 on a Mac has no associative arrays)
is_deployed() { [[ "$deployed" == *" $1 "* ]]; }
for name in shared jobs mineru airflow alerts; do
  stack="metamorph-ingestion-$name"
  status=$(aws cloudformation describe-stacks --stack-name "$stack" \
             --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || status=missing
  case "$status" in
    CREATE_COMPLETE|UPDATE_COMPLETE) pass "stack $stack: $status"; deployed+="$name " ;;
    *) fail "stack $stack: $status" ;;
  esac
done

# --- EFS: the access points -----------------------------------------------------------------------------------------

if is_deployed shared; then
  files=$(aws cloudformation list-exports --query "Exports[?Name=='metamorph-efs'].Value" --output text 2>/dev/null)
  count=$(aws efs describe-access-points --file-system-id "$files" \
            --query 'length(AccessPoints[?LifeCycleState==`available`])' --output text 2>&1) || count="$(first_line <<<"$count")"
  if [ "$count" = "$ACCESS_POINTS" ]; then
    pass "EFS $files has $count access points"
  else
    fail "EFS ${files:-?} has '$count' available access points, not $ACCESS_POINTS"
  fi
else
  skip "EFS access points (no shared stack)"
fi

# --- MinerU: stopped outside its window -----------------------------------------------------------------------------

param() {   # a parameter the mineru stack was deployed with
  aws cloudformation describe-stacks --stack-name metamorph-ingestion-mineru \
    --query "Stacks[0].Parameters[?ParameterKey=='$1'].ParameterValue" --output text
}
minutes() {   # cron(MINUTE HOUR day-of-month * ? *) -> minutes after midnight UTC
  local minute hour
  read -r minute hour _ <<<"$(sed -E 's/^cron\((.*)\)$/\1/' <<<"$1")"
  echo $((10#$hour * 60 + 10#$minute))
}

if is_deployed mineru; then
  start=$(minutes "$(param WindowStart)")
  if [ "$(date -u +%d)" = 01 ]; then end=$(minutes "$(param MonthlyWindowEnd)"); else end=$(minutes "$(param WindowEnd)"); fi
  now=$((10#$(date -u +%H) * 60 + 10#$(date -u +%M)))
  states=$(aws ec2 describe-instances --filters Name=tag:Name,Values=metamorph-mineru \
             Name=instance-state-name,Values=pending,running,stopping,stopped \
             --query 'Reservations[].Instances[].State.Name' --output text 2>&1)
  if [ "$(wc -w <<<"$states")" -ne 1 ]; then
    fail "MinerU: expected one instance named metamorph-mineru, found: ${states:-none}"
  elif [ "$now" -ge "$start" ] && [ "$now" -lt "$end" ]; then
    pass "MinerU instance is $states, inside its window ($(date -u +%H:%M) UTC)"
  elif [ "$states" = stopped ] || [ "$states" = stopping ]; then
    pass "MinerU instance is $states, outside its window ($(date -u +%H:%M) UTC)"
  else
    fail "MinerU instance is $states outside its window ($(date -u +%H:%M) UTC): the schedule did not stop it"
  fi
else
  skip "MinerU instance (no mineru stack)"
fi

# --- Airflow: the service has a running task ------------------------------------------------------------------------

if is_deployed airflow; then
  running=$(aws ecs describe-services --cluster "$CLUSTER" --services airflow \
              --query 'services[0].runningCount' --output text 2>&1)
  if [[ "$running" =~ ^[0-9]+$ ]] && [ "$running" -ge 1 ]; then
    pass "Airflow service has $running running task"
  else
    fail "Airflow service has no running task (runningCount: $(first_line <<<"$running"))"
  fi
else
  skip "Airflow service (no airflow stack)"
fi

echo
if [ "$failures" -eq 0 ]; then echo "all checks passed"; else echo "$failures check(s) failed"; fi
[ "$failures" -eq 0 ]
