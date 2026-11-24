# 04 The collection side's ingest DAG: upload instead of load; weekday working hours; MinerU's new window

Status: resolved
Blocked by: 01, 02
Spec: ../spec.md ("The ingest DAG on the collection side"; "MinerU" → the window)

## What

- Ingest DAG steps: discard ← collect (with export) → upload → discard. The load step leaves this DAG (ticket 05 loads on AWS). The ingest DAG no longer emits registry Datasets.
- Upload runs ticket 02's platform command in the platform image with the Docker launcher, given the Mac's AWS configuration (SSO, its token cache writable so it can refresh) and the blobs bucket (`metamorph-blobs-<account>`, chosen 2026-11-24 because the platform task can already read it; the weekly backup stays in the ops bucket); the bundle's S3 key is per connector and run.
- Schedules (job registry) move to weekday working hours WIB: PDF-reading jobs start 09:00–11:30 WIB; monthly full re-reads on the first weekday of the month; `catchup` stays off. The backup stays weekly, on a weekday after the window.
- MinerU's window in the mineru stack: weekdays 08:45–12:45 WIB (01:45–05:45 UTC); to 13:15 WIB on the first weekday of the month; a stop schedule repeating hourly outside the window. Document the one hand-start command in the stack's README.
- The existing rule "a PDF-reading job starts at least 60 minutes before the window ends" is kept against the new window, as are the health cadence expectations (adjust them to weekday schedules if they derive from them).
- The weekly backup (now collection-side, ticket 01) must work under the Docker launcher: today it runs only as an ECS task over EFS and is skipped locally. On the Mac it packs each connector's data/ (the existing SQLite-safe packing) and uploads to the same `backups/<date>/` keys, with the same SSO credentials as the upload.
- Compose: the local Airflow gets the bucket, the AWS config mount and MinerU's CloudFront address + key from the platform's .env (documented keys, no values committed).

## Acceptance

- Plain-data tests (tests/test_dag_jobs.py): every ingest job ends with an upload that writes the marker last; the upload command names the connector and run; every schedule is on weekdays in working hours; health still expects each connector on its cadence; the backup runs under the Docker launcher and uploads to `backups/<date>/<connector>.tgz`.
- Template tests (tests/test_ingestion_stacks.py): the weekday window, the first-weekday extension, the hourly stop; every PDF-reading job starts ≥ 60 min before the window ends.
- Full suite passes.
