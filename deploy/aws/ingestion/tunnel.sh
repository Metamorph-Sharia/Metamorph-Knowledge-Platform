#!/bin/bash
# A port on this Mac forwarded into the VPC through a running task, with ECS Exec and Session Manager
# (deploy/aws/ingestion/README.md). Nothing but the load balancer is open to the internet, so this is the way in.
#
#   deploy/aws/ingestion/tunnel.sh airflow 18080 8080              Airflow's UI at http://localhost:18080
#   deploy/aws/ingestion/tunnel.sh airflow 15432 "$DB_HOST:5432"   PostgreSQL (Aurora) at localhost:15432
#
# The first argument names the task definition, without "metamorph-": a service's (airflow) or a one-off
# task started with --enable-execute-command (ops).
# Needs the AWS CLI and its Session Manager plugin. Stop it with Ctrl-C.
set -euo pipefail

[ $# -eq 3 ] || { sed -n '2,10p' "$0" >&2; exit 2; }
name=$1 local_port=$2 target=$3
cluster="${CLUSTER:-metamorph}"

task=$(aws ecs list-tasks --cluster "$cluster" --family "metamorph-$name" --desired-status RUNNING \
         --query 'taskArns[0]' --output text)
[ "$task" != None ] || { echo "no metamorph-$name task is running: start it first" >&2; exit 1; }
runtime=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task" \
            --query 'tasks[0].containers[0].runtimeId' --output text)
session_target="ecs:${cluster}_${task##*/}_${runtime}"

if [[ "$target" == *:* ]]; then   # a host beyond the task, such as the database
  aws ssm start-session --target "$session_target" --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters "{\"host\":[\"${target%:*}\"],\"portNumber\":[\"${target##*:}\"],\"localPortNumber\":[\"$local_port\"]}"
else                              # a port of the task itself
  aws ssm start-session --target "$session_target" --document-name AWS-StartPortForwardingSession \
    --parameters "{\"portNumber\":[\"$target\"],\"localPortNumber\":[\"$local_port\"]}"
fi
