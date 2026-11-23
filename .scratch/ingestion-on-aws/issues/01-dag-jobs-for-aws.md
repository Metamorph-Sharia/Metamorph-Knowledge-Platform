# 01 DAG jobs: PDF flag, Reports in the window, weekly backup DAG

Status: ready-for-agent
Blocked by: none

Spec: `../spec.md`, the "DAG jobs" decision, plus user stories 16, 17 and 31.

## What to build
- A boolean field on the connector job description, saying whether the job reads PDFs (and so needs MinerU). Set it to true for OJK, BPK, BI, DSN-MUI, OJK register and Reports. Confirm each connector by reading its repository; it is true only if the connector calls `metamorph_pdf_text`.
- Move `ingest_reports` into MinerU's window: Mondays, after DSN-MUI's Monday 02:00. Fix any comments that name the old time.
- A new weekly DAG that runs the ops image as a container. It tars each connector's data directory, from the EFS root, to `s3://<ops bucket>/backups/<YYYY-MM-DD>/<connector>.tgz`.
  - The image is `metamorph/ops`; look for an existing `metamorph-ops` task family or ops image in the repo and follow it.
  - Under the local docker launcher, the DAG may be a no-op or skip cleanly. It is meant for ECS.
- Tests in the existing DAG job test file, in its style:
  - the flag is set where expected;
  - the backup DAG exists and is weekly;
  - its image has a task family.

## Acceptance
- `uv run pytest tests/test_dag_jobs.py` passes, along with the whole suite.
