"""What Airflow runs for each connector, as plain data. No Airflow import, so it is tested on its own.

On the collection host (docs/adr/0001-collection-on-a-residential-host.md) each job runs in its connector's own image
(built from the connector's repository), on weekdays in working hours WIB, while the laptop is awake:
  1. collect   the connector's scheduled run, then `export` of its bundle into /bundles, even when the run
               raised alerts, so the platform always gets the latest full snapshot
  2. upload    `metamorph upload-bundle`, in the platform image, as the owner's SSO session: the bundle goes to the
               blobs bucket under bundles/<connector>/<run>/, with its completion marker last. A failed upload (the
               session expired) is retried alone: the bundle stays on the disk
  3. discard   the bundle, once it is uploaded
Processing on AWS loads the uploaded bundles into the connector's layer: `metamorph load` (regulations, contract v2)
or `metamorph market load` (market data, market contract). A load's success updates the layer's registry, an Airflow
Dataset, which triggers the DAG that publishes it.

The layers, as Airflow Datasets, so the UI draws each from its connectors to what is published:
  regulation connectors → REGISTRY        → registry_build → PUBLISHED         (`published`)
                                                             → regulation_index → REGULATION_INDEX
  market connectors     → MARKET_REGISTRY → market_publish → PUBLISHED_MARKET  (`published_market`)
                                            → market_index   → MARKET_INDEX      (`retrieval_market`)

The connectors keep their state (SQLite stores, downloaded files) in their repositories' data/
directories, bind-mounted, so a scheduled run and a person's CLI run see the same store.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

PLATFORM_IMAGE = "metamorph-platform:dev"  # the platform's tasks: load, build, publish, health
REGISTRY = "metamorph://registry"  # the regulation layer's system of record (`registry`)
PUBLISHED = "metamorph://published"  # its read contract
MARKET_REGISTRY = "metamorph://market-registry"  # the market layer's system of record (`market`)
PUBLISHED_MARKET = "metamorph://published-market"  # its read contract
MARKET_INDEX = "metamorph://market-index"  # the retrieval layer's index of it (`retrieval_market`)
RETRIEVAL_IMAGE = "metamorph/retrieval:dev"  # Metamorph-Retrieval: the gateway and the market index's refresh
REGULATION_INDEX = "metamorph://regulation-index"  # the regulation index, judged before it is activated
MODELS = "/models"  # where the retrieval image keeps its embedding models
MODELS_VOLUME = "metamorph-models"
BUNDLES = "/bundles"
BUNDLES_VOLUME = "metamorph-bundles"
BUNDLES_KEY = "bundles"  # where uploaded bundles are kept in the blobs bucket, which the platform task can read: bundles/<connector>/<run id>/
LOAD_BUNDLES_SCHEDULE = "*/30 * * * *"  # how often the processing side looks for bundles to load (dags/load_bundles.py)
# A run's id (the bundle's name in the store) is the time its DAG run started, in the format of Airflow's ts_nodash, not
# the run's logical date: a scheduled run's logical date is the interval before it, so by hand and by schedule the
# ids would not sort by when the runs collected, and the loader takes bundles oldest first.
RUN_ID_TEMPLATE = "{{ dag_run.start_date.strftime('%Y%m%dT%H%M%S') }}"
EXPORT_FAILED = 3  # the collect task's exit code when no bundle could be written
NOTHING_LOADED = 4  # `metamorph load-pending`'s exit code for a pass that loaded and held nothing: the task is skipped
CONTAINER_HOME = "/home/connector"
# What every connector reads from its environment: how it reads a PDF's text. METAMORPH_PDF_LINES
# (metamorph_contract.printed_lines), and the engine with MinerU's settings (metamorph_pdf_text.SETTINGS). In
# Airflow's environment (compose.yaml), METAMORPH_PDF_LINES=extracted or METAMORPH_PDF_ENGINE=pymupdf rolls every
# connector back at once.
CONNECTOR_SETTINGS = (
    "METAMORPH_PDF_LINES",
    "METAMORPH_PDF_ENGINE",
    "METAMORPH_MINERU_URL",
    "METAMORPH_MINERU_API_KEY",
    "METAMORPH_MINERU_CACHE",
)
OJK_CREDENTIALS = f"{CONTAINER_HOME}/.config/ojk-connector/credentials"
TASK_CONTAINER = "main"  # on ECS, the one container of every task definition (deploy/aws/ingestion/jobs.yaml)


@dataclass(frozen=True)
class Mount:
    source: str  # a host path (bind) or a named volume
    target: str
    kind: str = "bind"  # bind | volume


class Layer(StrEnum):
    REGULATION = "regulation"  # contract v2 bundles: `metamorph load`, then the registry build
    MARKET = "market"  # market contract bundles: `metamorph market load`, then market_publish


@dataclass(frozen=True)
class ConnectorJob:
    dag_id: str
    connector: str  # the bundle's connector name: what `metamorph load` records
    image: str
    schedule: str
    collect: str  # shell: the connector's own scheduled run
    export: str  # shell, with {out}, {run_id} and {since}: when the job's last successful run started, or ""
    fails_from: int = 2  # collect's exit codes from this one up fail the task (below it: alerts, partial runs)
    mounts: tuple[Mount, ...] = ()
    secrets: tuple[str, ...] = ()  # environment variables passed through, never logged
    description: str = ""
    tags: tuple[str, ...] = ()
    layer: Layer = Layer.REGULATION
    # The connector calls metamorph_pdf_text, so it needs MinerU: its schedule must start inside MinerU's window
    # (deploy/aws/ingestion/mineru.yaml), which runs only then on AWS.
    reads_pdfs: bool = False
    # A monthly job: its schedule fires every weekday, and the DAG runs it on the first weekday that no successful
    # run of it has happened this month (monthly_pass_due), so a laptop asleep on the 1st catches up on a later day.
    # MinerU's window runs longer on the month's first three days, when it normally runs.
    monthly: bool = False


@dataclass(frozen=True)
class BackupJob:
    dag_id: str
    image: str
    schedule: str
    description: str


def passed_on(job: ConnectorJob) -> tuple[str, ...]:
    """The environment variables a job's container gets from Airflow's: its secrets, and every connector's settings."""
    return (*job.secrets, *CONNECTOR_SETTINGS)


def task_family(image: str) -> str:
    """The ECS task definition an image runs as: `metamorph/ojk-connector:dev` → `metamorph-ojk-connector`."""
    return image.rsplit(":", 1)[0].replace("/", "-")


def bundle_path(connector: str, run_id: str) -> str:
    return f"{BUNDLES}/{connector}/{run_id}"


def collect_command(job: ConnectorJob, run_id: str, since: str = "") -> list[str]:
    out = bundle_path(job.connector, run_id)
    script = "\n".join(
        [
            f"( {job.collect} )",
            "rc=$?",
            f'rm -rf "{out}"',  # a retry starts from an empty bundle directory
            f"{job.export.format(out=_quoted(out), run_id=run_id, since=_quoted(since))} || exit {EXPORT_FAILED}",
            f'[ "$rc" -lt {job.fails_from} ] || exit "$rc"',
        ]
    )
    return ["sh", "-c", script]


def registry_of(job: ConnectorJob) -> str:
    """The registry a job's load updates: the Dataset whose DAG publishes it."""
    return MARKET_REGISTRY if job.layer is Layer.MARKET else REGISTRY


def upload_command(job: ConnectorJob, run_id: str, bundles_bucket: str) -> list[str]:
    """The platform's command for the run's bundle: bundles/<connector>/<run>/ in the blobs bucket, marker last."""
    return ["upload-bundle", bundle_path(job.connector, run_id), f"s3://{bundles_bucket}/bundles"]


def monthly_pass_due(today: date, last_success: datetime | None) -> bool:
    """Whether a monthly job's weekday firing runs: no run of it has succeeded this calendar month."""
    return last_success is None or (last_success.year, last_success.month) != (today.year, today.month)


@dataclass(frozen=True)
class PendingLoad:
    """One task of the processing side's load_bundles DAG: a connector's uploaded bundles, loaded into its layer."""

    connector: str
    command: list[str]  # the platform's: `load-pending <prefix>`
    registry: str  # the Dataset a load updates

    @property
    def task_id(self) -> str:
        return f"load_{self.connector}"


def pending_loads(jobs: Iterable[ConnectorJob], bundles_bucket: str) -> list[PendingLoad]:
    """One load per connector. A connector's jobs share its prefix, so they share its load."""
    first_job_of: dict[str, ConnectorJob] = {}
    for job in jobs:
        first_job_of.setdefault(job.connector, job)
    return [
        PendingLoad(
            connector=connector,
            command=_load_pending_command(job, f"s3://{bundles_bucket}/{BUNDLES_KEY}/{connector}"),
            registry=registry_of(job),
        )
        for connector, job in first_job_of.items()
    ]


def _load_pending_command(job: ConnectorJob, prefix: str) -> list[str]:
    return ["market", "load-pending", prefix] if job.layer is Layer.MARKET else ["load-pending", prefix]


def discard_command(job: ConnectorJob, run_id: str) -> list[str]:
    return ["rm", "-rf", bundle_path(job.connector, run_id)]


def backup_job() -> BackupJob:
    """The weekly copy of the connectors' data to the ops bucket, from the collection host, after the week's ingests."""
    return BackupJob(
        dag_id="backup_connector_data",
        image=PLATFORM_IMAGE,  # it has boto3 and a shell
        # Fridays 07:00 UTC (14:00 WIB), after MinerU's window closes (06:15 UTC on the first weekday). A run that
        # started late in the window can still be writing a store, so the backup snapshots each SQLite file (PACK_DATA)
        # instead of copying it as it is
        schedule="0 7 * * 5",
        description="Weekly: each connector's data/ as a tarball in the ops bucket, backups/<date>/<connector>.tgz",
    )


# The backup's packing step: a connector's data directory as a tarball. A connector's SQLite store may be written
# while it is copied (an ingest may still be running), and a plain copy of its file can be torn or miss what is
# still in its -wal. So each SQLite file goes in as a snapshot taken with sqlite3's backup API (consistent, with the
# -wal folded in), and the -wal/-shm/-journal files are left out. A file with a SQLite extension that SQLite cannot
# open goes in as it is, with a warning. Run as `python - <directory> <tarball>`.
PACK_DATA = """\
import os, sqlite3, sys, tarfile, tempfile

root, out = sys.argv[1:3]
STORES = (".sqlite", ".sqlite3", ".db")
SIDECARS = ("-wal", "-shm", "-journal")


def snapshot(path, copy):
    source = sqlite3.connect(path, timeout=60)
    try:
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


with tempfile.TemporaryDirectory() as scratch, tarfile.open(out, "w:gz") as archive:
    for folder, folders, files in os.walk(root):
        folders.sort()
        for name in sorted(files):
            path = os.path.join(folder, name)
            arcname = os.path.relpath(path, root)
            if name.endswith(SIDECARS) and name.rsplit("-", 1)[0].endswith(STORES):
                continue
            if name.endswith(STORES):
                copy = os.path.join(scratch, "snapshot")
                try:
                    snapshot(path, copy)
                except sqlite3.Error as error:
                    print(f"warning: {arcname} is not read as SQLite ({error}); copied as it is", file=sys.stderr)
                else:
                    archive.add(copy, arcname=arcname)
                    os.remove(copy)
                    continue
            archive.add(path, arcname=arcname)
"""


def _data_directories(jobs: Sequence[ConnectorJob]) -> dict[str, str]:
    """Connector → its data directory in the container (the DSN-MUI jobs share one)."""
    data: dict[str, str] = {}
    for job in jobs:
        for mount in job.mounts:
            if mount.kind == "bind" and mount.target.startswith("/workspace/") and mount.target.endswith("/data"):
                data.setdefault(job.connector, mount.target)
    return data


def backup_mounts(jobs: Sequence[ConnectorJob]) -> list[Mount]:
    """The data directories the backup packs, each once, as the jobs mount them."""
    directories = set(_data_directories(jobs).values())
    mounts = {m.target: m for job in jobs for m in job.mounts if m.target in directories}
    return list(mounts.values())


def backup_command(jobs: Sequence[ConnectorJob], date: str) -> list[str]:
    """The backup task's command: one tarball per connector, uploaded to `backups/<date>/<connector>.tgz`.

    The task's entry point is `sh -c`, so the command is the script alone. Every tarball is tried; the task fails if
    any was not uploaded.
    """
    lines = [
        "rc=0",
        # boto3 is in the image (the platform's); the SSO session may write backups/* in $OPS_BUCKET
        """upload() { python -c 'import boto3, sys; boto3.client("s3").upload_file(*sys.argv[1:])' "$1" "$OPS_BUCKET" "$2"; }""",
        f"pack() {{ python - \"$1\" \"$2\" <<'PYTHON'\n{PACK_DATA}PYTHON\n}}",
    ]
    for connector, directory in _data_directories(jobs).items():
        tarball = f"/tmp/{connector}.tgz"
        lines.append(
            f'( pack "{directory}" {tarball} && upload {tarball} backups/{date}/{connector}.tgz && rm {tarball} ) || rc=1'
        )
    lines.append('exit "$rc"')
    return ["\n".join(lines)]


def ingest_jobs(workspace: str, *, ojk_credentials: str) -> list[ConnectorJob]:
    """`workspace`: the host directory holding the connector repositories (bind mounts are host paths)."""

    def data(repository: str) -> Mount:
        return Mount(f"{workspace}/{repository}/data", f"/workspace/{repository}/data")

    bundles = Mount(BUNDLES_VOLUME, BUNDLES, kind="volume")
    dsn = dict(
        connector="dsn-fatwa",
        image="metamorph/dsn-mui-connector:dev",
        reads_pdfs=True,
        export="dsn export --out {out} --run-id {run_id}",
        mounts=(data("DSN-MUI-Source-Connector"), bundles),
        tags=("dsn-mui",),
    )
    return [
        ConnectorJob(
            dag_id="ingest_ojk",
            connector="ojk",
            image="metamorph/ojk-connector:dev",
            reads_pdfs=True,
            # 09:00 WIB. Every schedule is on weekdays in working hours; a job that reads PDFs (reads_pdfs) starts in
            # MinerU's window, at least an hour before it ends
            schedule="0 2 * * 1-5",
            collect="ojk-connector run",
            export="ojk-connector export --format v2 --out {out} --run-id {run_id}",
            mounts=(data("OJK-Source-Connector"), Mount(ojk_credentials, OJK_CREDENTIALS), bundles),
            description="OJK via JDIH OJK (OJK's legal database): discover, read entries and official files, export",
            tags=("ojk",),
        ),
        ConnectorJob(
            dag_id="ingest_bpk",
            connector="bpk",
            image="metamorph/bpk-connector:dev",
            reads_pdfs=True,
            schedule="20 2 * * 1-5",
            collect="bpk-connector run",
            export="bpk-connector export --format v2 --out {out} --run-id {run_id}",
            mounts=(data("BPK-Source-Connector"), bundles),
            description="BPK: sitemaps, target checks, files, text extraction with OCR, export",
            tags=("bpk",),
        ),
        ConnectorJob(
            dag_id="ingest_bi",
            connector="bi-website",
            image="metamorph/bi-connector:dev",
            reads_pdfs=True,
            schedule="40 2 * * 1-5",
            collect="python -m src.init_db && python -m src.cli sync",
            export="python -m src.pipeline.exporter_v2 --out {out} --run-id {run_id}",
            fails_from=1,  # BI's CLI exits 1 only on an unhandled error
            mounts=(data("BI-Source-Connector"), bundles),
            secrets=("DATABASE_URL",),
            description="Bank Indonesia: newest regulations into BI's own database, then export",
            tags=("bi",),
        ),
        ConnectorJob(
            dag_id="ingest_dsn_fatwa",
            schedule="0 3 * * 1",  # weekly: DSN-MUI publishes a few fatwas a year
            collect="dsn sync --quiet",
            description="DSN-MUI fatwas: new or moved files (MinerU reads their Arabic too), export",
            **dsn,
        ),
        ConnectorJob(
            dag_id="ingest_dsn_fatwa_full",
            schedule="30 3 * * 1-5",  # monthly (see `monthly`), after the weekly run
            monthly=True,
            collect="dsn sync --all --refresh-index --quiet",
            description="DSN-MUI fatwas, full pass: re-download everything to catch silent re-uploads",
            **dsn,
        ),
        ConnectorJob(
            dag_id="ingest_ojk_register",
            connector="ojk-register",
            image="metamorph/ojk-register:dev",
            reads_pdfs=True,
            schedule="30 4 * * 1",  # weekly, Mondays: OJK publishes each list on no fixed day
            collect="ojk-register sync",  # exits 2 on a refusal or an edition it can't read: the task fails
            export="ojk-register export --out {out} --run-id {run_id}",
            mounts=(data("OJK-Register-Connector"), bundles),
            secrets=("OJK_REGISTER_CONTACT",),  # added to the connector's User-Agent, if set
            description="OJK's register of licensed fintech lenders: new editions from OJK's directory, export",
            tags=("ojk", "market"),
            layer=Layer.MARKET,
        ),
        ConnectorJob(
            dag_id="ingest_ojk_stats",
            connector="ojk-stats",
            image="metamorph/ojk-stats:dev",
            schedule="0 4 * * 1",  # weekly, Mondays, after the register: the portal updates its months on no fixed day
            collect="ojk-stats collect",  # exits 2 on a refusal: the task fails, and nothing is worked around
            export="ojk-stats export --out {out} --run-id {run_id}",
            mounts=(data("OJK-Stats-Connector"), bundles),
            secrets=("OJK_STATS_CONTACT",),  # added to the connector's User-Agent, if set
            description="OJK's statistics from its data portal: fintech lending and sharia banking series, export",
            tags=("ojk", "market"),
            layer=Layer.MARKET,
        ),
        ConnectorJob(
            dag_id="ingest_bi_seki",
            connector="bi-stats",
            image="metamorph/bi-stats:dev",
            schedule="45 3 * * 1",  # weekly, Mondays: picks up the edition a curator dropped in the inbox
            # bi.go.id refuses the connector, so a curator downloads each month's edition and drops it in
            # BI-Stats-Connector/data/inbox/ (option A, 2026-10-28). An edition already read is all unchanged
            collect="bi-stats import",
            export="bi-stats export --out {out} --run-id {run_id}",
            mounts=(data("BI-Stats-Connector"), bundles),
            description="BI's SEKI tables, from the editions curators download: the macro backdrop as series, export",
            tags=("bi", "market"),
            layer=Layer.MARKET,
        ),
        ConnectorJob(
            dag_id="ingest_reports",
            connector="reports",
            image="metamorph/reports:dev",
            reads_pdfs=True,
            # weekly, Mondays, just after DSN-MUI's weekly run: LPKSI comes yearly, OJK's press releases a few a week
            schedule="15 3 * * 1",
            # exits 2 on a refusal; a report MinerU can't read now is kept unread and read on a later run.
            # KEKSI and the roadmaps are imported by hand (`reports import`), into the same data/
            collect="reports sync",
            export="reports export --out {out} --run-id {run_id}",
            mounts=(data("Reports-Connector"), bundles),
            secrets=("REPORTS_CONTACT",),  # added to the connector's User-Agent, if set
            description="Regulators' reports (LPKSI, KEKSI, roadmaps) and OJK's press releases: the new ones, export",
            tags=("ojk", "bi", "market"),
            layer=Layer.MARKET,
        ),
        ConnectorJob(
            dag_id="ingest_bps_stats",
            connector="bps-stats",
            image="metamorph/bps-stats:dev",
            schedule="15 4 * * 1",  # weekly, Mondays: only the tables BPS changed are asked again
            # an hour a week: BPS answers slowly, so a run stops before its next table once the hour is spent, and the
            # next week's goes on. Exits 2 on a refusal or challenge: the task fails, nothing is worked around
            collect="bps-stats collect --for 60",
            # BPS's tables hold millions of values: the bundle carries the tables collected since the last success
            export="bps-stats export --out {out} --run-id {run_id} --since {since}",
            mounts=(data("BPS-Stats-Connector"), bundles),
            secrets=("BPS_STATS_CONTACT",),  # added to the connector's User-Agent, if set
            description="BPS's dynamic tables from bps.go.id: population, labour, prices, regions, as series, export",
            tags=("bps", "market"),
            layer=Layer.MARKET,
        ),
    ]


def _quoted(path: str) -> str:
    return f'"{path}"'
