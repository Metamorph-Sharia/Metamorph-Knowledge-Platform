"""The ingestion jobs Airflow runs, as plain data: commands, schedules and mounts, checked without Airflow."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from metamorph_pipeline.alerts import failure_message
from metamorph_pipeline.jobs import (
    BUNDLES,
    PLATFORM_IMAGE,
    TASK_CONTAINER,
    ConnectorJob,
    bundle_path,
    collect_command,
    ingest_jobs,
    passed_on,
    task_family,
)

WORKSPACE = "/Users/someone/Metamorph-Sharia"
CREDENTIALS = "/Users/someone/.config/ojk-connector/credentials"


@pytest.fixture
def jobs() -> dict[str, ConnectorJob]:
    return {job.dag_id: job for job in ingest_jobs(WORKSPACE, ojk_credentials=CREDENTIALS)}


def test_every_connector_has_a_scheduled_job(jobs) -> None:
    assert sorted(jobs) == ["ingest_bi", "ingest_bpk", "ingest_dsn_fatwa", "ingest_dsn_fatwa_full", "ingest_ojk"]
    assert {job.connector for job in jobs.values()} == {"ojk", "bpk", "bi-website", "dsn-fatwa"}


def test_each_connector_keeps_its_own_data_directory_and_ojk_its_token(jobs) -> None:
    ojk = jobs["ingest_ojk"]

    assert [(m.source, m.target) for m in ojk.mounts] == [
        (f"{WORKSPACE}/OJK-Source-Connector/data", "/workspace/OJK-Source-Connector/data"),
        (CREDENTIALS, "/home/connector/.config/ojk-connector/credentials"),
        ("metamorph-bundles", BUNDLES),
    ]


def test_every_connector_is_told_how_to_read_pdf_text_so_one_setting_rolls_it_back(jobs) -> None:
    assert all("METAMORPH_PDF_LINES" in passed_on(job) for job in jobs.values())
    assert all("METAMORPH_PDF_ENGINE" in passed_on(job) for job in jobs.values())
    assert passed_on(jobs["ingest_bi"])[:1] == ("DATABASE_URL",)


def test_every_setting_the_pdf_text_package_reads_is_passed_on() -> None:
    from metamorph_pdf_text import SETTINGS
    from metamorph_pipeline.jobs import CONNECTOR_SETTINGS

    assert set(SETTINGS) <= set(CONNECTOR_SETTINGS)


def test_on_ecs_an_image_runs_as_the_task_definition_named_after_it() -> None:
    assert task_family("metamorph/ojk-connector:dev") == "metamorph-ojk-connector"
    assert task_family(PLATFORM_IMAGE) == "metamorph-platform"


def test_every_image_a_dag_runs_has_its_task_definition_on_ecs(jobs) -> None:
    template = (Path(__file__).parents[1] / "deploy/aws/ingestion/jobs.yaml").read_text()
    defined = set(re.findall(r"^      Family: (\S+)$", template, re.MULTILINE))
    images = {job.image for job in jobs.values()} | {PLATFORM_IMAGE}

    assert {task_family(image) for image in images} <= defined
    assert re.findall(r"ContainerDefinitions:\n        - Name: (\S+)", template) == [TASK_CONTAINER] * len(defined)


def test_bundles_are_kept_per_connector_and_run() -> None:
    assert bundle_path("dsn-fatwa", "20261015T020000") == "/bundles/dsn-fatwa/20261015T020000"


def run(script: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(script, capture_output=True, text=True)


def job(collect: str, export: str = "mkdir -p {out} && echo {run_id} > {out}/manifest", fails_from: int = 2):
    return ConnectorJob("ingest_x", "x", "image", "@daily", collect=collect, export=export, fails_from=fails_from)


def test_a_bundle_is_exported_even_when_the_run_raised_alerts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("metamorph_pipeline.jobs.BUNDLES", str(tmp_path))

    result = run(collect_command(job("exit 1"), "r1"))  # 1: alerts or a partial run, below fails_from

    assert result.returncode == 0
    assert (tmp_path / "x" / "r1" / "manifest").read_text() == "r1\n"


def test_a_failed_run_still_exports_but_fails_the_task(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("metamorph_pipeline.jobs.BUNDLES", str(tmp_path))

    result = run(collect_command(job("exit 2"), "r1"))

    assert result.returncode == 2
    assert (tmp_path / "x" / "r1" / "manifest").exists()


def test_a_failed_export_fails_the_task_and_a_retry_starts_from_an_empty_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("metamorph_pipeline.jobs.BUNDLES", str(tmp_path))
    (tmp_path / "x" / "r1").mkdir(parents=True)
    (tmp_path / "x" / "r1" / "half-written").write_text("")

    assert run(collect_command(job("true", export="false"), "r1")).returncode == 3
    assert not (tmp_path / "x" / "r1").exists()


def test_a_failure_message_names_the_task_and_its_log() -> None:
    context = {
        "dag": type("Dag", (), {"dag_id": "ingest_ojk"}),
        "task_instance": type("Ti", (), {"task_id": "collect", "log_url": "http://airflow/log", "try_number": 2}),
        "run_id": "scheduled__2026-10-15",
        "exception": RuntimeError("exit 2"),
    }

    assert failure_message(context) == (
        "Metamorph: ingest_ojk.collect failed (run scheduled__2026-10-15, try 2): exit 2 — http://airflow/log"
    )
