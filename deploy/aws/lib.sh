# Shell helpers for deploying and operating Metamorph on AWS. Source it; do not run it:
#
#   cd Metamorph-Knowledge-Platform
#   export AWS_REGION=<region>                      # reference: ap-southeast-3
#   export METAMORPH_EXECUTION_ROLE=<role name>     # the ECS task execution role (reference: Project3EcsTaskExecutionRole)
#   export METAMORPH_OWNER_TAG=<owner>              # optional: tags every stack Owner=<owner> (the reference needs project3)
#   source deploy/aws/lib.sh
#
# It sets ACCOUNT and ROLE, and defines:
#   deploy STACK [cloudformation deploy args]   deploy deploy/aws/STACK.yaml as metamorph-STACK (ingestion/jobs -> metamorph-ingestion-jobs)
#   setting NAME                                read a Parameter Store value
#   secret NAME VALUE                           write a SecureString parameter
#   exported NAME                               read a CloudFormation export
#   run_task FAMILY SG_EXPORT COMMAND...        run metamorph-FAMILY once on cluster metamorph, wait, print its log and exit code
#
# Works in bash and zsh. Used by docs/deploy-from-scratch.md and deploy/aws/ingestion/README.md.
# Not yet run as a whole against a fresh account: the helpers are the ones the reference deployment used by hand.

if [ -z "${AWS_REGION:-}" ]; then
  echo "lib.sh: set AWS_REGION first" >&2
  return 1 2>/dev/null || exit 1
fi
export AWS_REGION
ACCOUNT=$(aws sts get-caller-identity --query Account --output text) || { echo "lib.sh: not signed in to AWS" >&2; return 1 2>/dev/null || exit 1; }
ROLE="arn:aws:iam::${ACCOUNT}:role/${METAMORPH_EXECUTION_ROLE:-<set METAMORPH_EXECUTION_ROLE>}"   # braces: in zsh, $ACCOUNT:r is a modifier

setting() { aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text; }
secret()  { aws ssm put-parameter --name "$1" --type SecureString --value "$2" --overwrite >/dev/null; }
exported() { aws cloudformation list-exports --query "Exports[?Name=='$1'].Value" --output text; }

deploy() {
  local stack="$1"; shift
  local tags=()
  [ -n "${METAMORPH_OWNER_TAG:-}" ] && tags=(--tags "Owner=$METAMORPH_OWNER_TAG")
  aws cloudformation deploy --stack-name "metamorph-${stack//\//-}" --template-file "deploy/aws/$stack.yaml" \
    "${tags[@]}" --no-fail-on-empty-changeset "$@"
}

run_task() {  # family (without metamorph-), the export of its security group, then the command, one word per argument
  local family="$1" sg="$2"; shift 2
  local net overrides id
  net="awsvpcConfiguration={subnets=[$(exported metamorph-subnets)],securityGroups=[$(exported "$sg")],assignPublicIp=ENABLED}"
  overrides=$(python3 -c 'import json, sys; print(json.dumps({"containerOverrides": [{"name": "main", "command": sys.argv[1:]}]}))' "$@")
  id=$(aws ecs run-task --cluster metamorph --launch-type FARGATE --task-definition "metamorph-$family" \
         --network-configuration "$net" --overrides "$overrides" --query 'tasks[0].taskArn' --output text)
  id=${id##*/}; echo "task $id"
  until aws ecs wait tasks-stopped --cluster metamorph --tasks "$id" 2>/dev/null; do :; done
  aws logs tail /metamorph --log-stream-name-prefix "metamorph-$family/" --since 1h | grep "$id"
  aws ecs describe-tasks --cluster metamorph --tasks "$id" \
    --query 'tasks[0].containers[].[name,exitCode,reason]' --output text
}
