"""The ingestion jobs Airflow runs, as plain data: commands, schedules and mounts, checked without Airflow."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from metamorph_pipeline.alerts import failure_message
from metamorph_pipeline.jobs import (
    BUNDLES,
    LOAD_BUNDLES_SCHEDULE,
    MARKET_REGISTRY,
    PLATFORM_IMAGE,
    PUBLISHED,
    PUBLISHED_MARKET,
    REGISTRY,
    TASK_CONTAINER,
    OPS_IMAGE,
    PACK_DATA,
    ConnectorJob,
    Layer,
    backup_command,
    backup_job,
    bundle_path,
    collect_command,
    ingest_jobs,
    load_command,
    passed_on,
    pending_loads,
    registry_of,
    task_family,
)

WORKSPACE = "/Users/someone/Metamorph-Sharia"
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
    assert load_command(jobs["ingest_ojk_register"], "r1") == ["market", "load", "/bundles/ojk-register/r1"]


def test_a_load_updates_its_layer_s_registry_which_its_own_dag_publishes(jobs) -> None:
    registries = {job.dag_id: registry_of(job) for job in jobs.values()}

    assert {registries[dag] for dag in ("ingest_ojk", "ingest_bpk", "ingest_bi", "ingest_dsn_fatwa")} == {REGISTRY}
    assert {registries[dag] for dag in ("ingest_ojk_register", "ingest_ojk_stats", "ingest_bi_seki",
                                        "ingest_bps_stats", "ingest_reports")} == {MARKET_REGISTRY}
    assert (REGISTRY, MARKET_REGISTRY, PUBLISHED, PUBLISHED_MARKET) == (
        "metamorph://registry", "metamorph://market-registry", "metamorph://published",
        "metamorph://published-market")


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
    images = {job.image for job in jobs.values()} | {PLATFORM_IMAGE, OPS_IMAGE}

    assert {task_family(image) for image in images} == defined
    # each definition has one "main" the DAGs override (BI statistics' also has the container that fills its inbox)
    assert re.findall(rf"^        - Name: {TASK_CONTAINER}$", template, re.MULTILINE) == [f"        - Name: {TASK_CONTAINER}"] * len(defined)


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


def minutes_after_midnight(cron: str) -> int:
    minute, hour = cron.split()[:2]
    return int(hour) * 60 + int(minute)


def test_the_jobs_that_read_pdfs_are_flagged_so_that_they_run_while_mineru_does(jobs) -> None:
    # Each connector's repository calls metamorph_pdf_text (checked 2026-11-23); the three statistics connectors read tables.
    readers = {"ingest_ojk", "ingest_bpk", "ingest_bi", "ingest_dsn_fatwa", "ingest_dsn_fatwa_full",
               "ingest_ojk_register", "ingest_reports"}

    assert {dag for dag, job in jobs.items() if job.reads_pdfs} == readers


def test_reports_reads_its_pdfs_on_mondays_inside_mineru_s_window_after_dsn_mui(jobs) -> None:
    reports, dsn = jobs["ingest_reports"], jobs["ingest_dsn_fatwa"]
    assert reports.schedule.split()[2:] == ["*", "*", "1"]
    assert minutes_after_midnight(dsn.schedule) < minutes_after_midnight(reports.schedule)


def test_a_weekly_job_copies_every_connector_s_data_to_the_ops_bucket() -> None:
    backup = backup_job()

    assert backup.dag_id == "backup_connector_data"
    assert backup.image == OPS_IMAGE
    assert task_family(backup.image) == "metamorph-ops"
    day_of_month, month, day_of_week = backup.schedule.split()[2:]
    assert (day_of_month, month) == ("*", "*") and day_of_week != "*"  # once a week, on one weekday


def test_the_backup_tars_each_connector_s_data_directory_once_to_a_dated_key(jobs) -> None:
    script = backup_command(list(jobs.values()), "2026-11-22")

    assert len(script) == 1  # the ops task's entry point is `sh -c`: its command is the script alone
    assert script[0].count("backups/2026-11-22/") == 9  # nine connectors; the two DSN-MUI jobs share one directory
    for connector, repository in {"ojk": "OJK-Source-Connector", "bi-website": "BI-Source-Connector",
                                  "dsn-fatwa": "DSN-MUI-Source-Connector", "reports": "Reports-Connector"}.items():
        assert f"/workspace/{repository}/data" in script[0]
        assert f"backups/2026-11-22/{connector}.tgz" in script[0]
    assert "$OPS_BUCKET" in script[0]



def pack(directory: Path, tarball: Path) -> None:
    """Runs the backup's packing step as the ops task does: the program on stdin, then the directory and the tarball."""
    subprocess.run([sys.executable, "-", str(directory), str(tarball)], input=PACK_DATA, text=True, check=True)


def test_the_backup_packs_a_consistent_copy_of_a_sqlite_store_that_is_being_written(tmp_path) -> None:
    data = tmp_path / "data"
    (data / "db").mkdir(parents=True)
    store = data / "db" / "connector.sqlite"
    live = sqlite3.connect(store, isolation_level=None)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, title TEXT)")
    live.executemany("INSERT INTO entries (title) VALUES (?)", [(f"Pasal {n}",) for n in range(500)])
    live.execute("PRAGMA wal_autocheckpoint=0")  # the writer is mid-run: its rows are in the -wal file, not the main one
    live.execute("INSERT INTO entries (title) VALUES ('newest')")
    assert (data / "db" / "connector.sqlite-wal").exists()
    (data / "raw").mkdir()
    (data / "raw" / "a.pdf").write_bytes(b"%PDF plain file")
    (data / "dsn.db").write_bytes(b"not a database, whatever the extension")  # kept as it is: the backup does not fail on it

    tarball = tmp_path / "out.tgz"
    pack(data, tarball)
    live.close()

    restored = tmp_path / "restored"
    with tarfile.open(tarball) as archive:
        archive.extractall(restored, filter="data")
        names = archive.getnames()
    assert not [name for name in names if name.endswith(("-wal", "-shm", "-journal"))]  # the copy stands alone
    copy = sqlite3.connect(restored / "db" / "connector.sqlite")
    assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert copy.execute("SELECT count(*), max(title) FROM entries").fetchone() == (501, "newest")  # the -wal's row too
    assert (restored / "raw" / "a.pdf").read_bytes() == b"%PDF plain file"
    assert (restored / "dsn.db").read_bytes() == b"not a database, whatever the extension"


def test_the_backup_script_packs_with_that_program_and_does_not_tar_a_live_store(jobs) -> None:
    script = backup_command(list(jobs.values()), "2026-11-22")[0]

    assert "tar -czf" not in script
    assert PACK_DATA.strip() in script
    assert script.count('pack "/workspace/') == 9  # one per connector


def test_the_backups_folder_is_dated_by_the_day_it_runs() -> None:
    # `ds` is the start of the data interval: for a weekly schedule, the Sunday a week before the run. Airflow is not
    # installed here, so the DAG file is read as text.
    source = (Path(__file__).parents[1] / "dags" / "backup.py").read_text()
    assert 'DATE = "{{ data_interval_end | ds }}"' in source
    assert "{{ ds }}" not in source


def test_the_backup_script_runs_under_sh_and_uploads_a_readable_tarball_per_connector(jobs, tmp_path) -> None:
    (tmp_path / "boto3.py").write_text(  # S3 is a directory: upload_file(file, bucket, key) copies it there
        "import os, shutil\n"
        "class Client:\n"
        "    def upload_file(self, path, bucket, key):\n"
        "        target = os.path.join(os.environ['FAKE_S3'], bucket, key)\n"
        "        os.makedirs(os.path.dirname(target), exist_ok=True)\n"
        "        shutil.copy(path, target)\n"
        "def client(name):\n"
        "    return Client()\n"
    )
    store = tmp_path / "ojk-data"
    store.mkdir()
    with sqlite3.connect(store / "ojk.sqlite") as db:
        db.execute("CREATE TABLE t (a)")
        db.execute("INSERT INTO t VALUES (1)")
    script = backup_command([jobs["ingest_ojk"]], "2026-11-22")[0]
    script = script.replace("/workspace/OJK-Source-Connector/data", str(store))
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "FAKE_S3": str(tmp_path / "s3"), "OPS_BUCKET": "ops"}

    done = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, check=False)

    assert done.returncode == 0, done.stderr
    with tarfile.open(tmp_path / "s3" / "ops" / "backups" / "2026-11-22" / "ojk.tgz") as archive:
        archive.extractall(tmp_path / "restored", filter="data")
    assert sqlite3.connect(tmp_path / "restored" / "ojk.sqlite").execute("SELECT a FROM t").fetchall() == [(1,)]


OPS_BUCKET = "metamorph-ops-example"


def test_processing_loads_each_connectors_pending_bundles_from_its_prefix_in_its_layer(jobs) -> None:
    loads = {load.connector: load for load in pending_loads(jobs.values(), OPS_BUCKET)}

    assert loads["ojk"].command == ["load-pending", f"s3://{OPS_BUCKET}/bundles/ojk"]
    assert loads["ojk-register"].command == ["market", "load-pending", f"s3://{OPS_BUCKET}/bundles/ojk-register"]
    assert loads["ojk"].registry == REGISTRY
    assert loads["ojk-register"].registry == MARKET_REGISTRY


def test_each_connector_has_one_load_even_when_it_has_two_jobs(jobs) -> None:
    # dsn-fatwa's weekly and monthly jobs upload to the same prefix: two loads would race for the same bundles
    loads = pending_loads(jobs.values(), OPS_BUCKET)

    assert [load.connector for load in loads].count("dsn-fatwa") == 1
    assert sorted(load.connector for load in loads) == sorted({job.connector for job in jobs.values()})
    assert len({load.task_id for load in loads}) == len(loads)


def test_a_load_s_prefix_is_where_the_upload_puts_the_connector_s_bundles(jobs) -> None:
    for load in pending_loads(jobs.values(), OPS_BUCKET):
        assert load.command[-1] == f"s3://{OPS_BUCKET}/bundles/{load.connector}"  # bundles/<connector>/<run id>/


def test_the_loads_run_every_half_hour() -> None:
    assert LOAD_BUNDLES_SCHEDULE == "*/30 * * * *"
