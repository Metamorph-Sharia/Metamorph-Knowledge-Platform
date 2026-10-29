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
    Layer,
    bundle_path,
    collect_command,
    ingest_jobs,
    load_command,
    passed_on,
    task_family,
)

WORKSPACE = "/Users/someone/Metamorph-Sharia"
# Images whose ECS task definition waits: the market data layer joins the AWS ingestion layer after every phase is
# built (docs/market-data-layer-plan.md, Step 10, deferred by the project owner on 2026-10-27).
ECS_DEFERRED = {"metamorph/ojk-register:dev", "metamorph/ojk-stats:dev", "metamorph/bi-stats:dev",
                "metamorph/bps-stats:dev", "metamorph/reports:dev"}
CREDENTIALS = "/Users/someone/.config/ojk-connector/credentials"


@pytest.fixture
def jobs() -> dict[str, ConnectorJob]:
    return {job.dag_id: job for job in ingest_jobs(WORKSPACE, ojk_credentials=CREDENTIALS)}


def test_every_connector_has_a_scheduled_job(jobs) -> None:
    assert sorted(jobs) == [
        "ingest_bi", "ingest_bi_seki", "ingest_bpk", "ingest_bps_stats", "ingest_dsn_fatwa", "ingest_dsn_fatwa_full",
        "ingest_ojk", "ingest_ojk_register", "ingest_ojk_stats", "ingest_reports",
    ]
    assert {job.connector for job in jobs.values()} == {
        "ojk", "bpk", "bi-website", "dsn-fatwa", "ojk-register", "ojk-stats", "bi-stats", "bps-stats", "reports",
    }


def test_health_expects_every_connector_on_its_cadence(jobs) -> None:
    from metamorph_platform.domain.health import CADENCE

    assert {job.connector for job in jobs.values()} == set(CADENCE)


def test_the_register_job_syncs_and_loads_into_the_market_layer(jobs) -> None:
    register = jobs["ingest_ojk_register"]

    assert (register.image, register.layer, register.collect) == (
        "metamorph/ojk-register:dev", Layer.MARKET, "ojk-register sync",
    )
    assert register.export == "ojk-register export --out {out} --run-id {run_id}"
    assert [(m.source, m.target) for m in register.mounts] == [
        (f"{WORKSPACE}/OJK-Register-Connector/data", "/workspace/OJK-Register-Connector/data"),
        ("metamorph-bundles", BUNDLES),
    ]
    assert "OJK_REGISTER_CONTACT" in passed_on(register)


def test_the_statistics_job_collects_from_the_portal_and_loads_into_the_market_layer(jobs) -> None:
    stats = jobs["ingest_ojk_stats"]

    assert (stats.image, stats.layer, stats.collect, stats.schedule) == (
        "metamorph/ojk-stats:dev", Layer.MARKET, "ojk-stats collect", "15 3 * * 1",
    )
    assert stats.export == "ojk-stats export --out {out} --run-id {run_id}"
    assert [(m.source, m.target) for m in stats.mounts] == [
        (f"{WORKSPACE}/OJK-Stats-Connector/data", "/workspace/OJK-Stats-Connector/data"),
        ("metamorph-bundles", BUNDLES),
    ]
    assert "OJK_STATS_CONTACT" in passed_on(stats)


def test_a_bundle_loads_into_its_own_layer(jobs) -> None:
    assert load_command(jobs["ingest_ojk"], "r1") == ["load", "/bundles/ojk/r1"]
    assert load_command(jobs["ingest_ojk_register"], "r1") == [
        "market", "load", "/bundles/ojk-register/r1", "--publish",
    ]


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
    images = {job.image for job in jobs.values()} - ECS_DEFERRED | {PLATFORM_IMAGE}

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


def test_the_macro_jobs_load_into_the_market_layer(jobs) -> None:
    seki, bps = jobs["ingest_bi_seki"], jobs["ingest_bps_stats"]

    assert (seki.image, seki.layer, seki.collect) == ("metamorph/bi-stats:dev", Layer.MARKET, "bi-stats import")
    assert seki.export == "bi-stats export --out {out} --run-id {run_id}"
    assert (bps.image, bps.layer) == ("metamorph/bps-stats:dev", Layer.MARKET)
    assert bps.collect == "bps-stats collect --for 60"  # an hour a week, so a first collection ends over weeks
    assert bps.export == "bps-stats export --out {out} --run-id {run_id} --since {since}"
    assert [m.source for m in bps.mounts] == [f"{WORKSPACE}/BPS-Stats-Connector/data", "metamorph-bundles"]
    assert "BPS_STATS_CONTACT" in passed_on(bps)
    assert [m.source for m in seki.mounts][0] == f"{WORKSPACE}/BI-Stats-Connector/data"  # its inbox, data/inbox/


def test_an_export_may_take_the_start_of_the_last_successful_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("metamorph_pipeline.jobs.BUNDLES", str(tmp_path))
    since = job("true", export="mkdir -p {out} && echo since={since} > {out}/manifest")

    run(collect_command(since, "r1", since="2026-10-20T03:15:00+00:00"))

    assert (tmp_path / "x" / "r1" / "manifest").read_text() == "since=2026-10-20T03:15:00+00:00\n"


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


def test_the_reports_job_syncs_lpksi_and_loads_into_the_market_layer(jobs) -> None:
    reports = jobs["ingest_reports"]

    assert (reports.image, reports.layer, reports.collect) == ("metamorph/reports:dev", Layer.MARKET, "reports sync")
    assert reports.export == "reports export --out {out} --run-id {run_id}"
    assert [m.source for m in reports.mounts] == [f"{WORKSPACE}/Reports-Connector/data", "metamorph-bundles"]
    assert {"METAMORPH_MINERU_URL", "REPORTS_CONTACT"} <= set(passed_on(reports))

