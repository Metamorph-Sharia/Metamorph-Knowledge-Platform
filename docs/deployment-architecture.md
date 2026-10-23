# The deployed architecture, with MinerU

**Date:** 2026-10-21 · **Status:** the architecture as built in steps 1–8 of [mineru-extraction-plan.md](mineru-extraction-plan.md). MinerU isn't deployed yet: step 9 runs first, on SageMaker AI ([aws-step9-sagemaker-guide.md](aws-step9-sagemaker-guide.md)) · **For:** whoever deploys the stack with MinerU

This page describes the system as it is meant to run once MinerU reads every connector's PDFs:
- the services, and the clean-architecture rings inside each package;
- where MinerU plugs in;
- what changes on the day it is deployed: configuration only;
- why step 9 on SageMaker AI leaves all of this as it is.

## Contents

1. [The system](#the-system)
2. [The rings in each package](#the-rings-in-each-package)
3. [How MinerU plugs in](#how-mineru-plugs-in)
4. [Deploying MinerU](#deploying-mineru)
5. [Step 9 on SageMaker AI and the deployed architecture](#step-9-on-sagemaker-ai-and-the-deployed-architecture)
6. [Architecture review, 2026-10-21](#architecture-review-2026-10-21)
7. [Rollback](#rollback)

## The system

```
 Sources (OJK, BPK, BI, DSN-MUI websites)
     │ fetched by each connector's scheduled run
     ▼
 ┌ Airflow (schedules only) ─ each task is a container on the "metamorph" network ──────────────────────┐
 │                                                                                                      │
 │  Connector image (OJK, BPK, BI, DSN-MUI)          MinerU service (compose profile "mineru")          │
 │    collect → re-read changed PDFs → export  ──HTTP V1──►  mineru-kit api-server, 4.0.12, standard tier│
 │    metamorph-pdf-text inside: ExtractPdf                  --disable-image-analysis, --api-key         │
 │    data/  (bind-mounted): store, PDFs,                    Linux + NVIDIA GPU (≥ 8 GB VRAM)            │
 │           mineru-cache/ (every reading, kept)                                                         │
 │        │ contract v2.1 bundle (plain text + page markers + extraction)                                │
 │        ▼                                                                                              │
 │  Platform image: metamorph load → build (parse with parser 6 → resolve → validity → publish)          │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────┘
     │                                   │
     ▼                                   ▼
 PostgreSQL 16: ingest, registry,     Object store (S3 API; SeaweedFS locally): text and file blobs
 curation, published
     │
     ├─► Curation JSON API (platform image) ◄── Curation web app (Metamorph-Curation-Web, Next.js)
     └─► Knowledge & Retrieval layer (another repository): reads published.*, embeds provision_unit
```

| Service | Image | Runs | MinerU's part |
|---|---|---|---|
| Connectors | `metamorph/<connector>-connector`, built from each repository | Per Airflow task | Each one calls MinerU over HTTP when `METAMORPH_PDF_ENGINE=mineru`, and keeps every reading in its own `data/mineru-cache/` |
| MinerU | `metamorph/mineru:4.0.12`, from [`docker/mineru/Dockerfile`](../docker/mineru/Dockerfile) | On the GPU host. On AWS, only in the ingest window | Reads PDFs. It has no state worth keeping: the readings live in the connectors' caches |
| Platform | `metamorph-platform` | Per Airflow task, and the API | None. It stores the `extraction` record a bundle carries, and never calls MinerU |
| Airflow | `apache/airflow:2.10.5` | Always on | Passes the MinerU settings on to every connector task ([`dags/metamorph_pipeline/jobs.py`](../dags/metamorph_pipeline/jobs.py)) |
| PostgreSQL, object store, curation API and web | as in [`compose.yaml`](../compose.yaml) | Always on | None |

**On AWS** ([aws-deployment-guide.md](aws-deployment-guide.md)), each box is an ECS service or task, and PostgreSQL is Aurora Serverless v2. The core (the web app, the API, the database) deploys first. The ingestion layer ([deploy/aws/ingestion](../deploy/aws/ingestion/README.md)) plugs into it later: Airflow runs every DAG task as an ECS task (`METAMORPH_TASK_LAUNCHER=ecs`), and each task definition holds its volumes (EFS) and settings (Parameter Store). The rings below don't change: only the outermost one, `dags/metamorph_pipeline/containers.py`, knows where a container runs.

The Knowledge & Retrieval layer reads `published.*` only ([published-schema.md](published-schema.md)). It never sees which engine read a PDF, except through `published.text.extraction`.

## The rings in each package

Every package follows the same rule: **source-code dependencies point inward only.** Inner rings import the standard library and rings further in. Only adapters import a framework or an outside library. Only the composition root knows every concrete class.

```
 domain  ←  application  ←  adapters  ←  composition root (wiring, config, CLI, DAGs)
 pure rules   use cases + ports   HTTP, PostgreSQL, PyMuPDF, MinerU   reads the environment, builds the rest
```

| Package | Domain | Application | Adapters | Composition root | Enforced by |
|---|---|---|---|---|---|
| **Platform** `src/metamorph_platform` | `domain/`: structure (parser 6), citations, dates, the publish gate, validity | `application/`: load, parse, resolve, settle, validity, publish, curate; `ports.py` | `adapters/postgres`, `adapters/blobs` (S3), `adapters/api` (FastAPI) | `wiring.py`, `config.py`, `cli.py` | [`tests/test_architecture.py`](../tests/test_architecture.py) |
| **Contract** `packages/metamorph-contract` | The shared language: the normalized document and bundle types, the JSON Schemas, `printed_text` | | | | Dependency-light by design: jsonschema only |
| **PDF text** `packages/metamorph-pdf-text` | `domain/`: `Page`, `Block`, `clean`, `render`, `aligned`, `page_quality` | `application/`: `ExtractPdf`, `request_for`; ports `LayoutReader`, `ResultCache` | `adapters/`: `MinerUReader`, `PyMuPdfReader`, `FileResultCache`, the vocabulary | `environment.py`: `wants_mineru`, `from_environment` | [`tests/test_architecture.py`](../packages/metamorph-pdf-text/tests/test_architecture.py), with a check that it catches an outward import |
| **BPK** connector | `domain/`: file roles, identity, freshness, text quality | `application/`: use cases; port `TextExtractor`; its own `Extraction` DTO | `adapters/extraction/`: `PdfTextExtractor`, `OcrTextExtractor`, `ArchiveTextExtractor`, `MinerUTextExtractor` | `wiring.py` | its `tests/test_architecture.py` |
| **OJK**, **BI**, **DSN-MUI** connectors | not in rings | | | | none: see [the review](#architecture-review-2026-10-21) |

**What crosses each boundary** is plain data, never a framework's type:

| Boundary | Data |
|---|---|
| MinerU → `MinerUReader` | MinerU's `middle_json`. It stops in the adapter, which translates it to our `Page` and `Block`. |
| `LayoutReader` → `ExtractPdf` | `Reading`: our `Page`s and the mode MinerU resolved |
| `ExtractPdf` → connector | `ExtractedPdf`: plain page strings, the method, an `Extraction` record |
| Connector → platform | A contract v2.1 bundle: a text blob with page markers, and `TextRef.extraction` |
| Platform → Knowledge layer | `published.*` rows, the `provision_unit` and `edge` views |

So MinerU could be replaced, or upgraded across a breaking change, by changing one adapter. The cleaning rules, the parser and the published schema wouldn't change.

## How MinerU plugs in

1. **The use case `ExtractPdf`** reads a PDF through the `LayoutReader` port. It checks each page against the PDF's own text layer, a second `LayoutReader` (`PyMuPdfReader`), and keeps every reading in the `ResultCache` port.
2. **The adapters** are `MinerUReader` (the HTTP client for MinerU's V1 API) and `FileResultCache`: `{cache}/{pdf sha256}/{version}-{tier}-{ocr mode}.json`.
3. **The composition root** `from_environment(environ)` builds the use case from the settings below. Each connector asks `wants_mineru(environ)` first. Under `pymupdf` it doesn't build `ExtractPdf` at all and runs its own extraction, unchanged. That is what makes the rollback byte-identical.
4. **Each connector** hands the use case its PDFs from behind its own boundary:

   | Connector | Where | How |
   |---|---|---|
   | BPK | `adapters/extraction/mineru.py::MinerUTextExtractor`, behind its `TextExtractor` port | `wiring.build_extractor` chooses it under `mineru`. ZIP annexes are still unpacked by `ArchiveTextExtractor` |
   | OJK | `pdf_text.py::extract_text_with`, chosen in `sources/jdih/source.py` | The JDIH source builds `ExtractPdf` once, in its constructor |
   | BI | `src/pipeline/extractor.py::read` | Built once (`_mineru()`); used by both `reextract_records` and `reextract_database` |
   | DSN-MUI | `dsn_ingest/extract.py::extract_pdf` | Built once (`_environment_extractor()`), or passed in by a test. Arabic lines go to the side file, as before |

5. **A MinerU that can't be reached** raises `ExtractionUnavailable`. The task fails and Airflow retries it. Nothing falls back to the other engine, so no text is half switched.

## Deploying MinerU

Deploying it is configuration. No code changes.

### The host

- Linux with an NVIDIA GPU of at least 8 GB VRAM, 16 GB RAM or more, and the NVIDIA Container Toolkit.
- An NVIDIA driver of **580 or newer.** The image installs `mineru[full]==4.0.12`, whose vLLM build needs CUDA 13. Step 9's readings were made with this same build if SageMaker's driver was 580 or newer: check the first line of the job's `step9.log`. If SageMaker used the older vLLM 0.19.1 build, the cached readings stay valid. New files would then be read by a different build of the same MinerU version, which may differ slightly.
- The same host, or one the connectors reach on the compose network.

### The steps

1. **Build and start MinerU:**
   ```bash
   docker compose --profile mineru build mineru
   docker compose --profile mineru up -d mineru        # healthy once the models are loaded, up to 5 minutes
   ```
   The image holds the pinned models (`opendatalab/MinerU-4_models_torch`, `opendatalab/MinerU2.5-Pro-2605-1.2B`, both Apache 2.0). Image analysis is off, as in step 9.
2. **Put step 9's readings in place:** each connector's `data/mineru-cache/`, from `step9-mineru-cache.tgz` ([the guide's Phase 7](aws-step9-sagemaker-guide.md#phase-7-the-live-rollout-on-the-mac)). With them, nothing already read is read again.
3. **Set the connectors' settings** in the stack's `.env`, which Airflow passes on to every connector task:

   | Setting | Development (this Mac) | Deployed |
   |---|---|---|
   | `METAMORPH_PDF_ENGINE` | `pymupdf` until step 9; then `mineru` | `mineru` |
   | `METAMORPH_MINERU_URL` | `http://host.docker.internal:8010` (MinerU runs natively, `docker/mineru/run-dev.sh`) | `http://mineru:8010`, on the compose network |
   | `METAMORPH_MINERU_API_KEY` | optional | required: the same key the MinerU container starts with, from the secret store |
   | `METAMORPH_MINERU_CACHE` | `data/mineru-cache`, in each connector's `data/` | the same, on persistent, backed-up storage: it holds every reading |
   | `METAMORPH_PDF_LINES` | `printed` | `printed` |

4. **Rebuild the connector images,** so they carry the current code: `docker compose --profile connectors build`.
5. **Unpause the ingest DAGs.** From then on, a new or changed PDF is read by MinerU in its connector's scheduled run. An unchanged one comes from the cache.

### Before offering the service to anyone outside the team

- **Attribution:** "Text extraction by MinerU", visible in the curation web app and the README. MinerU's license requires it for an online service to third parties (plan step 12).
- **The Mac's model stays on the Mac.** Its VLM is a third party's GGUF conversion with no stated license, for development only. Every reading that is published comes from the pinned image's models, whether made on SageMaker in step 9 or by the MinerU container afterwards.

## Step 9 on SageMaker AI and the deployed architecture

**SageMaker AI is temporary infrastructure for one batch job, and it changes nothing in the architecture above.** It acts as a rented MinerU plus a batch run of the connectors' own re-extraction commands. Its only lasting product is the cache files, which `FileResultCache` reads like any other.

| Question | Answer |
|---|---|
| Does any package's code know about SageMaker? | No. Nothing under `src/`, `packages/` or any connector's source refers to it. The SageMaker code is in `docker/sagemaker/` (`step9.sh`, `train_entry.py`, `launch_job.py`, `load-scratch.sh`) and `docker/aws/stage-upload.sh`. These are operations scripts in the outermost ring. Nothing imports them, and they can be deleted after step 9. |
| Does it use a different code path? | No. It runs each connector's own CLI (`reparse`, `extract --again`, BI's `reextract_records`, DSN-MUI's `reextract.py`, then each `export`), with the same settings the deployed stack uses: `METAMORPH_PDF_ENGINE=mineru`, `METAMORPH_MINERU_URL`, `METAMORPH_MINERU_CACHE`. The connectors' composition roots don't know whether MinerU runs on SageMaker, the Mac or the GPU host. |
| Does it use a different MinerU? | No. It installs the same pinned `mineru[full]==4.0.12` with the same tier, the same models and `--disable-image-analysis` as the production image. The one exception is the vLLM build on a driver older than 580 (see [The host](#the-host)). |
| What does it hand over? | Three things. Each connector's `data/mineru-cache/`, which the deployed connectors read as cache hits. The bundles, which are loaded into a scratch database (`metamorph_step9`) for validation only. And logs. |
| Does it touch live data? | No. The live database and object store stay on the Mac and aren't uploaded. The validation loads into `metamorph_step9` (`load-scratch.sh` refuses any other database). The live rollout runs later, on the Mac, from the cache. |
| Does it change the compose stack, Airflow or the schema? | No. `compose.yaml`'s `mineru` service, the DAGs' `CONNECTOR_SETTINGS` and migration 0013 were all built in steps 3–8 for the deployed architecture, before SageMaker came up. |

**What keeps the hand-over valid.** The cache key is the PDF's SHA-256, the engine, MinerU's version plus the translation's revision (`4.0.12+t1`), the tier and the OCR mode. Until the deployed MinerU has taken over, keep these the same:
- MinerU's version, and `TRANSLATION` in `adapters/mineru_reader.py`. A change to either makes every cached reading a miss.
- The policy `request_for` and its 20% rule, which choose the tier and the OCR mode.
- The server's options, which the key doesn't record: the `standard` tier, `--disable-image-analysis`, and vLLM's PyTorch sampler (`VLLM_USE_FLASHINFER_SAMPLER=0`). The production Dockerfile and `step9.sh` set the same ones.

Cleaning, rendering and the parser are **not** in the key. A fix to any of them after step 9 is applied by re-running the connectors' re-extraction against the cache, with no GPU.

## Architecture review, 2026-10-21

The review used Robert C. Martin's Clean Architecture checklist: the dependency rule, the boundaries, the data that crosses them, and the layers. **Overall: good.** The MinerU work kept the dependency rule everywhere it was already enforced, and added one more enforced package.

**Checked and passing:**
- **The dependency rule is enforced by tests** in the platform, `metamorph-pdf-text` and BPK, and all three pass. `metamorph-pdf-text`'s test now also checks that it catches an outward import, as the platform's does.
- **The domain of `metamorph-pdf-text` is pure.** It imports only the standard library: no `httpx`, no `pymupdf`, no MinerU.
- **The application depends on its ports, not on adapters.** `LayoutReader` and `ResultCache` are `Protocol`s, each with real implementations: MinerU and PyMuPDF, and the file cache and the tests' in-memory one. The adapters raise the application's own errors (`ExtractionFailed`, `ExtractionUnavailable`).
- **MinerU's JSON stops in its adapter.** `mineru_layout.py` is the only module that reads it.
- **BPK is the model connector.** `ExtractPdf` sits behind BPK's own `TextExtractor` port as one more adapter. BPK's application ring keeps its own `Extraction` DTO, so it doesn't import the contract.
- **The platform doesn't depend on `metamorph-pdf-text`.** It uses the package for its tests only (a dev dependency). A bundle's `extraction` reaches it as contract data.
- **The step 9 scripts are outermost.** See [the section above](#step-9-on-sagemaker-ai-and-the-deployed-architecture).

**Findings, by priority.** None blocks deployment.

1. **Medium: OJK, BI and DSN-MUI aren't in rings, and nothing checks their dependencies.** MinerU enters each at the one function that already read PDFs, as the plan chose ("the connector's own boundary stays as it is"). But each one builds `ExtractPdf` where it reads the environment, not in one composition root:
   - OJK builds it in the JDIH source's constructor;
   - BI and DSN-MUI build it behind module-level caches (`_mineru()`, `_environment_extractor()`).

   **Impact:** low today. Each connector has one place to change, and OJK and DSN-MUI accept an `ExtractPdf` from a test.

   **Suggestion:** when one of them is next restructured, give it BPK's shape: a `TextExtractor` port, an adapter, a `wiring.py`, and an architecture test. Not before step 9, which freezes the code its cache key depends on.
2. **Low: `step9.sh` calls a function inside BI.** It runs `src.pipeline.reextract.reextract_records` with `python -c`, because BI's `reextract` CLI also re-reads BI's database, and SageMaker has none. The script is temporary and in the outermost ring, and a rename would fail loudly at the first run. A `reextract --records-only` option in BI's CLI would be cleaner if step 9 ever has to run again.
3. **Low: the cache key doesn't record the server's options or the vLLM build.** Today, matching options are a rule kept by two files: `docker/mineru/Dockerfile` and `docker/sagemaker/step9.sh`. Recording the options in the key, or in the `Extraction` record, would make the rule checkable. Changing the key now would invalidate step 9's readings, so leave it until after the rollout.

**Not recommended:** extra interfaces for single implementations, such as an interface over `from_environment` or over each connector's settings. The two ports in `metamorph-pdf-text` are worth having because each has two real implementations. No other interface is.

## Rollback

All of these are configuration too:
- **The engine, for every connector at once:** set `METAMORPH_PDF_ENGINE=pymupdf` in the stack's `.env`, then re-extract, export and load. The texts are byte-identical to the ones from before MinerU.
- **The MinerU service:** `docker compose --profile mineru stop mineru`. Connector tasks then fail and retry, rather than switching engines unseen.
- **The readings stay in the caches,** so going forward again reads nothing twice.

The details are in [the plan's Rollback section](mineru-extraction-plan.md#rollback).
