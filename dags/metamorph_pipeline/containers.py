"""Airflow's side of a Metamorph task: a container on the stack's network. Every task is one.

Airflow only schedules. Connectors run in their own images and the platform in its own, so neither
depends on what is installed in Airflow, and each can be run by hand with `docker run` the same way.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount as DockerMount

from metamorph_pipeline.jobs import Mount

PLATFORM_IMAGE = "metamorph-platform:dev"
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


def container(
    task_id: str,
    image: str,
    command: Sequence[str],
    *,
    mounts: Sequence[Mount] = (),
    secrets: Sequence[str] = (),
    **task_arguments,
) -> DockerOperator:
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


def platform(task_id: str, command: Sequence[str], *, mounts: Sequence[Mount] = (), **task_arguments) -> DockerOperator:
    """`metamorph …` in the platform image."""
    return container(task_id, PLATFORM_IMAGE, command, mounts=mounts, secrets=PLATFORM_SECRETS, **task_arguments)
