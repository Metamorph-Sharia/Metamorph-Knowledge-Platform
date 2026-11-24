# 02 Bundles travel through S3: upload, load from S3, load pending

Status: ready-for-agent
Blocked by: none
Spec: ../spec.md ("The ingest DAG on the collection side" → Upload; "Loading on the processing side")

## What

Platform changes only (the platform owns bundle transport, with its existing S3 adapter):

1. **Upload a bundle:** a platform command that copies a bundle directory to an S3 location `s3://<bucket>/bundles/<connector>/<run>/` and writes the completion marker `_COMPLETE` as the last object. Idempotent (a retry re-uploads and rewrites the marker). An AWS authentication failure (expired SSO session) exits with a message telling the operator to run `aws sso login`.
2. **Load from S3:** `metamorph load` and `metamorph market load` accept an `s3://` location as well as a directory: download to scratch, load as now, record the S3 location as the bundle's URI.
3. **Load pending:** a new use case + command `metamorph load-pending <s3 prefix for one connector>` (with the market layer chosen the way `market load` chooses it). List the connector's bundles; ignore those without `_COMPLETE`; skip those already loaded (the ledger refuses them: BundleAlreadyLoaded); load the rest oldest first by run id; stop at the first failure, leaving later bundles for the next pass. Report counts (loaded, skipped, held) as JSON; exit non-zero when it held a bundle.

Keep the use case in the application layer behind a small port for "list and fetch bundles"; S3 is an adapter.

## Acceptance

- Use-case tests against in-memory ports and a fake bundle store (prior art: tests/test_load_bundle.py, tests/test_load_market_bundle.py): marker missing → ignored; already loaded → skipped; oldest first; a failure holds later ones and the next pass resumes; counts right; market bundles go to the market layer.
- S3 adapter behaviour tested with a fake/stubbed client, no network.
- Full suite passes.
