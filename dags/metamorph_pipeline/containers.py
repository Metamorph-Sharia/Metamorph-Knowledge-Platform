"""Airflow's side of a Metamorph task: a container. Every task is one.

Airflow only schedules. Connectors run in their own images and the platform in its own, so neither
depends on what is installed in Airflow, and each can be run by hand the same way.

METAMORPH_TASK_LAUNCHER chooses where the container runs:
  docker  (the default) on the stack's network, through the host's Docker: the local Compose stack;
  ecs     as an ECS task on Fargate (deploy/aws). The image's task definition holds its volumes (EFS) and its
          settings (Parameter Store), so a DAG passes only the command; `mounts` and `secrets` are Docker's.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from airflow.models import BaseOperator
from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount as DockerMount

from metamorph_pipeline.jobs import PLATFORM_IMAGE, TASK_CONTAINER, Mount, task_family

NETWORK = "metamorph"
DOCKER_URL = "unix://var/run/docker.sock"
# Read from Airflow's own environment (compose.yaml) and passed on unlogged.
PLATFORM_SECRETS = (
    "METAMORPH_DATABASE_URL",
    "METAMORPH_S3_ENDPOINT_URL",
    "METAMORPH_S3_BUCKET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
)
LAUNCHER = os.environ.get("METAMORPH_TASK_LAUNCHER", "docker")
if LAUNCHER not in ("docker", "ecs"):
    raise RuntimeError(f"METAMORPH_TASK_LAUNCHER is {LAUNCHER!r}: docker or ecs")


def required_setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set: see Metamorph-Knowledge-Platform/.env.example")
    return value


def host_path(name: str) -> str:
    """A host directory for a Docker bind mount. On ECS the task definitions mount their own volumes."""
    return required_setting(name) if LAUNCHER == "docker" else ""


def container(
    task_id: str,
    image: str,
    command: Sequence[str],
    *,
    mounts: Sequence[Mount] = (),
    secrets: Sequence[str] = (),
    **task_arguments,
) -> BaseOperator:
    if LAUNCHER == "ecs":
        return _ecs_task(task_id, image, command, **task_arguments)
    return DockerOperator(
        task_id=task_id,
        image=image,
        command=list(command),
        docker_url=DOCKER_URL,
        network_mode=NETWORK,
        mounts=[DockerMount(target=m.target, source=m.source, type=m.kind) for m in mounts],
        mount_tmp_dir=False,  # Airflow runs in a container: its temp dir isn't a path the Docker host knows
        private_environment={name: os.environ[name] for name in secrets if name in os.environ},
        auto_remove="success",
        **task_arguments,
    )


def platform(task_id: str, command: Sequence[str], *, mounts: Sequence[Mount] = (), **task_arguments) -> BaseOperator:
    """`metamorph …` in the platform image."""
    return container(task_id, PLATFORM_IMAGE, command, mounts=mounts, secrets=PLATFORM_SECRETS, **task_arguments)


def _ecs_task(task_id: str, image: str, command: Sequence[str], **task_arguments) -> EcsRunTaskOperator:
    family = task_family(image)
    return EcsRunTaskOperator(
        task_id=task_id,
        task_definition=family,
        cluster=required_setting("METAMORPH_ECS_CLUSTER"),
        launch_type="FARGATE",
        overrides={"containerOverrides": [{"name": TASK_CONTAINER, "command": list(command)}]},
        network_configuration={
            "awsvpcConfiguration": {
                "subnets": required_setting("METAMORPH_ECS_SUBNETS").split(","),
                "securityGroups": [required_setting("METAMORPH_ECS_SECURITY_GROUP")],
                "assignPublicIp": "ENABLED",  # no NAT gateway: the task reaches the sources, ECR and S3 itself
            }
        },
        awslogs_group=required_setting("METAMORPH_ECS_LOG_GROUP"),
        awslogs_stream_prefix=f"{family}/{TASK_CONTAINER}",  # the task's log, shown in Airflow's
        **task_arguments,
    )
