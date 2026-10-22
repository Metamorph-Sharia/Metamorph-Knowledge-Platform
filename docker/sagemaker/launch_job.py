"""Starts the step 9 training job (docs/aws-step9-sagemaker-guide.md, Phase 4), with the same settings as the
console's Create training job form. From a Studio terminal, where boto3 and the execution role are at hand:

    python launch_job.py --bucket sagemaker-ap-southeast-3-123456789012 [--name metamorph-step9-1]

The job runs on demand: the account has no Spot. A job started again with the same checkpoint folder resumes from
the readings already made there.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3

REGION = "ap-southeast-3"
# AWS's Deep Learning Containers in Jakarta. The job only needs its Python and SageMaker's training toolkit:
# MinerU gets a virtualenv of its own.
IMAGE = (
    "907027046896.dkr.ecr.ap-southeast-3.amazonaws.com/pytorch-training:2.10.0-gpu-py313-cu130-ubuntu22.04-sagemaker"
)
STUDIO_METADATA = Path("/opt/ml/metadata/resource-metadata.json")  # in every Studio space: its domain and space
PREFIX = "metamorph-step9"
MAX_RUN_SECONDS = 2 * 24 * 3600  # the run is estimated at 15-30 hours; a cap of $102 at $2.12 an hour
VOLUME_GB = 100  # MinerU's environment and models (~25 GB), the data (~6 GB unpacked twice), the bundles


def main() -> None:
    arguments = _arguments()
    root = f"s3://{arguments.bucket}/{PREFIX}"
    job = {
        "TrainingJobName": arguments.name,
        "RoleArn": arguments.role or _execution_role(),
        "AlgorithmSpecification": {"TrainingImage": IMAGE, "TrainingInputMode": "File"},
        "HyperParameters": {
            "sagemaker_program": '"train_entry.py"',
            "sagemaker_submit_directory": f'"{root}/code/sagemaker-code.tar.gz"',
            "sagemaker_region": f'"{REGION}"',
        },
        "Environment": {"RUN_ID": arguments.run_id, "MINERU_CONCURRENCY": str(arguments.concurrency)},
        "InputDataConfig": [
            {
                "ChannelName": "inputs",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": f"{root}/inputs/",
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            }
        ],
        "OutputDataConfig": {"S3OutputPath": f"{root}/output/"},
        "ResourceConfig": {"InstanceType": arguments.instance, "InstanceCount": 1, "VolumeSizeInGB": VOLUME_GB},
        "CheckpointConfig": {"S3Uri": f"{root}/checkpoints/", "LocalPath": "/opt/ml/checkpoints"},
        "StoppingCondition": {"MaxRuntimeInSeconds": MAX_RUN_SECONDS},
    }
    boto3.client("sagemaker", region_name=REGION).create_training_job(**job)
    print(f"Started {arguments.name}: SageMaker AI console → Training → Training jobs")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bucket", required=True, help="the bucket holding metamorph-step9/")
    parser.add_argument("--name", default="metamorph-step9-1", help="the job's name, new for every job")
    parser.add_argument("--run-id", default="step9", help="the bundles' run id: new for a rerun (step9-2)")
    parser.add_argument("--instance", default="ml.g5.2xlarge")
    parser.add_argument("--concurrency", type=int, default=1, help="MinerU parse jobs at once")
    parser.add_argument("--role", help="the execution role's ARN (default: the role this terminal runs as)")
    return parser.parse_args()


def _execution_role() -> str:
    """The Studio execution role this terminal runs as. Its full ARN may hold a path ("service-role/") that only
    IAM knows, so IAM is asked; a role that may not read IAM gets it from the Studio domain instead."""
    arn = boto3.client("sts", region_name=REGION).get_caller_identity()["Arn"]
    if ":assumed-role/" not in arn:
        raise SystemExit(f"Not running as a role ({arn}): pass --role with the execution role's ARN")
    name = arn.split(":assumed-role/")[1].split("/")[0]
    try:
        return boto3.client("iam").get_role(RoleName=name)["Role"]["Arn"]
    except Exception:  # noqa: BLE001 - IAM refused, as company roles often do
        pass
    try:
        domain = json.loads(STUDIO_METADATA.read_text())["DomainId"]
        settings = boto3.client("sagemaker", region_name=REGION).describe_domain(DomainId=domain)
        return settings["DefaultUserSettings"]["ExecutionRole"]
    except Exception as error:  # noqa: BLE001 - neither knows: tell where the ARN is shown instead
        raise SystemExit(
            f"Can't read role {name}'s ARN from IAM or the Studio domain ({error}). Pass --role with the ARN "
            "shown in the SageMaker AI console under Domains → your domain → User profiles → your profile → "
            "Execution role."
        ) from error


if __name__ == "__main__":
    main()
