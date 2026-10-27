"""What Airflow runs for each connector, as plain data. No Airflow import, so it is tested on its own.

Each job runs in its connector's own image (built from the connector's repository):
  1. collect   the connector's scheduled run, then `export` of its bundle into /bundles, even when the run
               raised alerts, so the platform always gets the latest full snapshot
  2. load      in the platform image, into the connector's layer: `metamorph load` (regulations, contract v2,
               then the registry build) or `metamorph market load --publish` (market data, market contract)
  3. discard   the bundle, once it is loaded (a failed load keeps it for inspection)

The connectors keep their state (SQLite stores, downloaded files) in their repositories' data/
directories, bind-mounted, so a scheduled run and a person's CLI run see the same store.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

PLATFORM_IMAGE = "metamorph-platform:dev"  # the platform's tasks: load, build, health
BUNDLES = "/bundles"
BUNDLES_VOLUME = "metamorph-bundles"
EXPORT_FAILED = 3  # the collect task's exit code when no bundle could be written
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
    MARKET = "market"  # market contract bundles: `metamorph market load --publish`


@dataclass(frozen=True)
class ConnectorJob:
    dag_id: str
    connector: str  # the bundle's connector name: what `metamorph load` records
    image: str
    schedule: str
    collect: str  # shell: the connector's own scheduled run
    export: str  # shell, with {out} and {run_id}
    fails_from: int = 2  # collect's exit codes from this one up fail the task (below it: alerts, partial runs)
    mounts: tuple[Mount, ...] = ()
    secrets: tuple[str, ...] = ()  # environment variables passed through, never logged
    description: str = ""
    tags: tuple[str, ...] = ()
    layer: Layer = Layer.REGULATION


def passed_on(job: ConnectorJob) -> tuple[str, ...]:
    """The environment variables a job's container gets from Airflow's: its secrets, and every connector's settings."""
    return (*job.secrets, *CONNECTOR_SETTINGS)


def task_family(image: str) -> str:
    """The ECS task definition an image runs as: `metamorph/ojk-connector:dev` → `metamorph-ojk-connector`."""
    return image.rsplit(":", 1)[0].replace("/", "-")


def bundle_path(connector: str, run_id: str) -> str:
    return f"{BUNDLES}/{connector}/{run_id}"


def collect_command(job: ConnectorJob, run_id: str) -> list[str]:
    out = bundle_path(job.connector, run_id)
    script = "\n".join(
        [
            f"( {job.collect} )",
            "rc=$?",
            f'rm -rf "{out}"',  # a retry starts from an empty bundle directory
            f"{job.export.format(out=_quoted(out), run_id=run_id)} || exit {EXPORT_FAILED}",
            f'[ "$rc" -lt {job.fails_from} ] || exit "$rc"',
        ]
    )
    return ["sh", "-c", script]


def load_command(job: ConnectorJob, run_id: str) -> list[str]:
    """The platform's command for the job's bundle, in the job's layer."""
    bundle = bundle_path(job.connector, run_id)
    return ["market", "load", bundle, "--publish"] if job.layer is Layer.MARKET else ["load", bundle]


def discard_command(job: ConnectorJob, run_id: str) -> list[str]:
    return ["rm", "-rf", bundle_path(job.connector, run_id)]


def ingest_jobs(workspace: str, *, ojk_credentials: str) -> list[ConnectorJob]:
    """`workspace`: the host directory holding the connector repositories (bind mounts are host paths)."""

    def data(repository: str) -> Mount:
        return Mount(f"{workspace}/{repository}/data", f"/workspace/{repository}/data")

    bundles = Mount(BUNDLES_VOLUME, BUNDLES, kind="volume")
    dsn = dict(
        connector="dsn-fatwa",
        image="metamorph/dsn-mui-connector:dev",
        export="dsn export --out {out} --run-id {run_id}",
        mounts=(data("DSN-MUI-Source-Connector"), bundles),
        tags=("dsn-mui",),
    )
    return [
        ConnectorJob(
            dag_id="ingest_ojk",
            connector="ojk",
            image="metamorph/ojk-connector:dev",
            schedule="0 1 * * *",  # 08:00 WIB; every ingest runs in MinerU's window, 00:30–03:15 UTC
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
            schedule="20 1 * * *",
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
            schedule="40 1 * * *",
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
            schedule="0 2 * * 1",  # weekly: DSN-MUI publishes a few fatwas a year
            collect="dsn sync --quiet",
            description="DSN-MUI fatwas: new or moved files (MinerU reads their Arabic too), export",
            **dsn,
        ),
        ConnectorJob(
            dag_id="ingest_dsn_fatwa_full",
            schedule="30 2 1 * *",  # monthly, after the weekly run; the window runs to 04:30 on the 1st
            collect="dsn sync --all --refresh-index --quiet",
            description="DSN-MUI fatwas, full pass: re-download everything to catch silent re-uploads",
            **dsn,
        ),
        ConnectorJob(
            dag_id="ingest_ojk_register",
            connector="ojk-register",
            image="metamorph/ojk-register:dev",
            schedule="45 2 * * 1",  # weekly, Mondays: OJK publishes each list on no fixed day
            collect="ojk-register sync",  # exits 2 on a refusal or an edition it can't read: the task fails
            export="ojk-register export --out {out} --run-id {run_id}",
            mounts=(data("OJK-Register-Connector"), bundles),
            secrets=("OJK_REGISTER_CONTACT",),  # added to the connector's User-Agent, if set
            description="OJK's register of licensed fintech lenders: new editions from OJK's directory, export",
            tags=("ojk", "market"),
            layer=Layer.MARKET,
        ),
    ]


def _quoted(path: str) -> str:
    return f'"{path}"'
