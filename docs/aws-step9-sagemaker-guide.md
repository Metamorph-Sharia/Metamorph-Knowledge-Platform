# Running step 9 on Amazon SageMaker AI (Jakarta)

**Date:** 2026-10-21 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Status:** guide written, on-demand only (the account has no Spot); nothing created on AWS yet · **Plan:** [mineru-extraction-plan.md](mineru-extraction-plan.md), step 9 onward · **With EC2 instead:** [aws-step9-guide.md](aws-step9-guide.md) (CLI), [aws-step9-console-guide.md](aws-step9-console-guide.md) (console)

This guide is for an AWS account whose access is limited to **Amazon SageMaker AI**, with no EC2, Session Manager, Docker or Spot capacity. Step 9 re-extracts every PDF the four connectors hold with MinerU. On this Mac that takes 2–3 days, and its vision model is a development-only conversion. Here the GPU work runs in SageMaker, and the results come back to the Mac.

**Nothing is fetched from the sources again.** Each connector's data is copied up, and each connector runs only its offline re-extraction (`reparse`, `extract --again`, `reextract`) against that copy.

**SageMaker AI is used for step 9 only.** It is a one-off, rented GPU that fills each connector's MinerU cache. The deployed architecture, with MinerU as a service beside the connectors, is unchanged by it: see [deployment-architecture.md](deployment-architecture.md#step-9-on-sagemaker-ai-and-the-deployed-architecture).

## Contents

1. [The design](#the-design)
2. [What it costs](#what-it-costs)
3. [Phase 0: check what your SageMaker access allows](#phase-0-check-what-your-sagemaker-access-allows)
4. [Phase 1: on the Mac, prepare the upload](#phase-1-on-the-mac-prepare-the-upload)
5. [Phase 2: a CPU space, and the upload to S3](#phase-2-a-cpu-space-and-the-upload-to-s3)
6. [Phase 3: the go / no-go on a GPU space](#phase-3-the-go--no-go-on-a-gpu-space)
7. [Phase 4: the training job (the run)](#phase-4-the-training-job-the-run)
8. [Phase 5: watch it](#phase-5-watch-it)
9. [Phase 6: the results, back to the Mac](#phase-6-the-results-back-to-the-mac)
10. [Phase 7: the live rollout, on the Mac](#phase-7-the-live-rollout-on-the-mac)
11. [Phase 8: clean up](#phase-8-clean-up)
12. [What can go wrong](#what-can-go-wrong)

## The design

```
 Mac                                     SageMaker AI (Jakarta)
 ───                                     ──────────────────────
 docker/aws/stage-upload.sh ──upload──►  Studio JupyterLab space, CPU (ml.t3.medium): files in and out
   source.tgz, data-<repo>.tgz ×4,         └─► S3: s3://sagemaker-ap-southeast-3-<account>/metamorph-step9/
   bi.dump, sagemaker-code.tar.gz                 inputs/  code/  checkpoints/  output/
                                         Studio JupyterLab space, GPU (ml.g5.2xlarge): the 1-hour go / no-go
                                         Training job, on demand (ml.g5.2xlarge): the run
                                           docker/sagemaker/step9.sh, natively: MinerU (vLLM) + 4 connectors (uv)
                                           readings → checkpoints/ (synced; a new job resumes from them)
 docker/sagemaker/load-scratch.sh ◄────  output/<job>/output/model.tar.gz
   → metamorph_step9: the comparison       step9-bundles.tgz, step9-mineru-cache.tgz, logs/
 docker/aws/reextract-all.sh             (the live rollout reads step9-mineru-cache.tgz: no GPU needed)
```

**Why this shape:**
- **A training job,** not a notebook, runs the long part. It runs unattended and bills only while it runs: it stops by itself when the run is done, and a notebook space left running would keep billing. It runs **on demand**, since the account has no Spot, so nothing interrupts it.
- **The readings live in the job's checkpoint folder.** SageMaker copies it to S3 as the job goes. If the job fails or reaches its maximum runtime, a new job given the same folder gets the readings back and skips every file already read.
- **Everything runs natively, because SageMaker has no Docker.** MinerU gets its own virtualenv, and each connector its own `uv` environment, built from the same lock files as the Docker images. [`docker/sagemaker/step9.sh`](../docker/sagemaker/step9.sh) does all of it, and the same script runs in a Studio terminal (the go / no-go) and in the training job ([`train_entry.py`](../docker/sagemaker/train_entry.py)).
- **No Postgres on SageMaker.** BI's own database holds 62 PDFs, and all 62 are in BI's records too, so the job reads them there. BI's database is re-read on the Mac at rollout, from the same readings.
- **Loading and parsing run on the Mac.** That's CPU work, with no reason to pay GPU prices for it. [`load-scratch.sh`](../docker/sagemaker/load-scratch.sh) loads the bundles into a scratch database, `metamorph_step9`, next to the live one; the live one is untouched.
- **MinerU's image analysis is off** (`--disable-image-analysis`) everywhere: here, in the production image, and on the Mac. It writes descriptions of pictures as if they were the page's text. The cache key doesn't record server options, so every reading in one run must be made the same way.

**What has been tested, on the Mac (2026-10-21):**
- `step9.sh` in its go / no-go mode, on a real staged upload, against the Mac's MinerU. It unpacked the inputs, built all four connectors' native `uv` environments from their lock files, linked their caches, and ran the benchmark through BPK's environment.
- In those environments: BI's records-only re-extraction imports without a database, and OJK's and DSN-MUI's commands are there.
- The launcher's options, and the request it sends, printed with AWS faked: on demand, checkpoints, a 2-day maximum. The scratch loader refuses to run if its database would be the live one.
- The fixes found in the 20-document BPK sample: see the plan's risks.

Nothing has run on SageMaker, so the console steps are written from AWS's documentation and are untested.

## What it costs

These are Jakarta prices from AWS's price list, 2026-10-21, on demand.

| Item | Rate | Use | Cost |
|---|---|---|---|
| **Training job, ml.g5.2xlarge, on demand** | $2.120 an hour | 15–30 hours of reading, plus about 20 minutes of setup | **about $33–65** |
| Go / no-go: JupyterLab space, ml.g5.2xlarge | $2.120 an hour | about 1.5 hours | about $3 |
| Uploads and downloads: JupyterLab space, ml.t3.medium | $0.060 an hour | a few hours | under $0.50 |
| Storage: the training job's 100 GB volume | $0.168 per GB-month | the job's days | about $1.50 |
| Storage: the spaces' volumes, 60 GB in all | $0.168 per GB-month | about a week | about $2.50 |
| S3: inputs, checkpoints, outputs, about 25 GB | $0.025 per GB-month | a month | under $1 |
| **Total** | | | **about $40–75** |

**The hours** are from the census in [the EC2 guide](aws-step9-guide.md#what-it-costs). 26,773 pages will be OCR'd and 55,772 read from their characters. The A10G's MinerU speed is unknown, so the go / no-go in Phase 3 measures it.

**Without Spot, the hours are the cost,** so the savings are in not paying for idle time and not reading twice:
- **The go / no-go comes first.** An hour on the GPU space ($2) settles the driver, the install, internet access and the speed before a $33–65 job starts.
- **The concurrency that the go / no-go measured best.** If `MINERU_CONCURRENCY=2` reads the benchmark faster than 1, the whole run is that much shorter. The hourly price is the same.
- **ml.g5.2xlarge, not ml.g5.xlarge.** The xlarge has the same A10G for $1.76 an hour, but 16 GB of memory. MinerU's vLLM and the four connectors running side by side need more than that. Running out of memory partway would cost more than the 17% saving.
- **Nothing is read twice.** The checkpoint folder keeps every reading, so a failed job or a rerun after a fix (Phase 6) pays only for the files not yet read.
- **No space is left running.** Spaces bill by the hour while running, the GPU one at the job's own price.

**Guardrails:**
1. The training job ends by itself when the run is done.
2. Its maximum runtime is capped at 2 days, so a stuck job can cost at most $102. A run that needs longer resumes in a new job.
3. Stop the GPU space as soon as the go / no-go is done. The job itself needs no space running.
4. If your account has Studio's idle shutdown, it stops forgotten spaces.

## Phase 0: check what your SageMaker access allows

Company accounts vary, and each of these can block the run. Check them first, and take anything missing to your AWS administrator.

| Check | Where | What you need |
|---|---|---|
| **Studio** opens | SageMaker AI console (Jakarta) → **Studio** → your user profile → **Open Studio** | A domain and a user profile |
| **GPU quotas** | **Service Quotas** → Amazon SageMaker, searching `g5.2xlarge`. If you can't open Service Quotas, ask the administrator. | At least 1 for **ml.g5.2xlarge for training job usage** (the run) and for **ml.g5.2xlarge for JupyterLab spaces apps** (the go / no-go). The Spot quota isn't needed. New accounts often have 0. Request them days ahead. |
| **Training jobs** allowed | Console → **Training → Training jobs → Create training job** opens | `sagemaker:CreateTrainingJob`, and the execution role can be passed to it |
| **S3** through the execution role | In a Studio terminal (Phase 2): `aws s3 ls s3://sagemaker-ap-southeast-3-<account>/` | Read and write in SageMaker's default bucket (or any bucket the role may use) |
| **Internet** from Studio and from jobs | In a Studio terminal: `curl -sI https://pypi.org \| head -1` and `curl -sI https://huggingface.co \| head -1` | Both `HTTP/2 200`. A VPC-only domain without a NAT gateway can't install MinerU or download its models; that needs the administrator. |
| **Space storage** | When creating a JupyterLab space: **Storage (GB)** | 20 GB for the CPU space, 40 GB for the GPU space. The domain's maximum may be lower; the administrator sets it. |

## Phase 1: on the Mac, prepare the upload

1. **Pause the ingest DAGs** (Airflow, http://localhost:8080) from now until the rollout, Phase 7. A file fetched after the upload has no reading from SageMaker, and the rollout would read it on the Mac.
2. **Freeze the code the cache key depends on** until Phase 7: [Phase 0, step 4 of the EC2 guide](aws-step9-guide.md#phase-0-before-aws-the-mac).
3. **Make the upload folder,** with the compose stack running:
   ```bash
   cd ~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform
   docker/aws/stage-upload.sh                   # writes ~/metamorph-step9-upload, about 6 GB
   ```

   | File | What it is |
   |---|---|
   | `source.tgz` | The workspace's repositories, uncommitted work included; no `data/`, `.env`, virtualenvs or EDA folder |
   | `data-<repo>.tgz` × 4 | Each connector's `data/` without its old `exports/` and without any MinerU cache |
   | `bi.dump`, `source-revisions.txt` | BI's database, and each repository's commit, for the record |
   | `sagemaker-code.tar.gz` | The training job's code, `train_entry.py` and `step9.sh`, and its launcher, `launch_job.py` |

## Phase 2: a CPU space, and the upload to S3

1. **Open Studio.** In the SageMaker AI console (region **Asia Pacific (Jakarta)**), choose **Studio**, pick your user profile, then **Open Studio**.
2. **Create a small JupyterLab space** for moving files.
   - In Studio, choose **JupyterLab** in the left bar, then **Create JupyterLab space**.
   - **Name:** `metamorph-files`. **Sharing:** Private.
   - Open it. Set **Instance** to `ml.t3.medium` and **Storage (GB)** to `20`, then **Run space**, then **Open JupyterLab**.
3. **Upload the files.**
   - In JupyterLab's file browser (left), choose **New folder** and name it `upload`. Open it.
   - Choose the **Upload files** button (the up arrow) and select the eight files from `~/metamorph-step9-upload`.
   - Keep the tab open until each upload's progress bar is done. At 20 Mbit/s, 6 GB takes about 40 minutes.
4. **Copy them to S3.** Choose **File → New → Terminal**, and run:
   ```bash
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   BUCKET=sagemaker-ap-southeast-3-$ACCOUNT
   aws s3 ls "s3://$BUCKET" >/dev/null 2>&1 || aws s3 mb "s3://$BUCKET" --region ap-southeast-3
   aws s3 cp ~/upload/sagemaker-code.tar.gz "s3://$BUCKET/metamorph-step9/code/"
   aws s3 cp --recursive ~/upload "s3://$BUCKET/metamorph-step9/inputs/" --exclude sagemaker-code.tar.gz
   aws s3 ls "s3://$BUCKET/metamorph-step9/" --recursive --human-readable
   echo "$BUCKET"                                # note it: the next phases use it
   ```
   If `aws s3 mb` is refused, ask the administrator which bucket the execution role may write to, and use that one.
5. **Free the space's disk:** `rm -rf ~/upload`. Then stop the space: **Stop space** on its page.

## Phase 3: the go / no-go on a GPU space

This is a one-hour test of the whole MinerU set-up before the long run:
- the NVIDIA driver;
- installing MinerU and downloading its models;
- the internet access both need;
- the speed on the two BPK files timed on the Mac in step 8.

1. **Create a second space:** `metamorph-gpu`, Private. Set **Instance** to `ml.g5.2xlarge` and **Storage (GB)** to `40`, then **Run space** and **Open JupyterLab**.
2. **Run the check** in a new terminal:
   ```bash
   BUCKET=sagemaker-ap-southeast-3-<account>
   mkdir -p ~/inputs && aws s3 cp --recursive "s3://$BUCKET/metamorph-step9/inputs/" ~/inputs/
   aws s3 cp "s3://$BUCKET/metamorph-step9/code/sagemaker-code.tar.gz" - | tar -xzf - -C ~ step9.sh
   INPUTS=~/inputs MODE=check bash ~/step9.sh
   ```
   It takes 30–45 minutes, mostly installing MinerU (about 10 GB) and downloading its models (about 3 GB).
   - **The first line** shows the GPU and its driver. With driver 580 or newer, MinerU gets the build tested on the Mac (vLLM 0.28, CUDA 13). With an older driver, it gets vLLM 0.19.1 built for CUDA 12.8.
   - **The benchmark lines** come last, and are also in `~/step9-work/out/logs/benchmark.log`.
3. **Go when:**
   - the output shows `version`, `tiers` and four `models` lines;
   - the scan's line, `timed standard auto → ocr … 50 pages`, shows **150 s or less**.

   Then estimate the run's hours:
   - **OCR'd pages:** 26,773 ÷ (3,000 ÷ the scan's seconds);
   - **Born-digital pages:** 55,772 ÷ (2,580 ÷ the seconds on `timed standard auto → txt … 43 pages`).

   Each gives minutes; add them.
4. **If it warns `no C compiler`:** vLLM needs one. Run `sudo apt-get install -y gcc` if your space allows it, or `conda install -y -c conda-forge gcc`, then run the check again. The training job's image has `gcc`.
5. **Stop the space now:** its page → **Stop space**. It bills $2.12 an hour while running. Delete it once the run has worked.

## Phase 4: the training job (the run)

Start the job one of two ways. Both give the same job.

### A. In the console form

1. In the SageMaker AI console (Jakarta), choose **Training → Training jobs → Create training job**.
2. **Job settings:**
   - **Job name:** `metamorph-step9-1`.
   - **IAM role:** your Studio execution role (**Choose an existing role**).
3. **Algorithm options:**
   - **Algorithm source:** **Your own algorithm container in ECR**.
   - **Container path:** `907027046896.dkr.ecr.ap-southeast-3.amazonaws.com/pytorch-training:2.10.0-gpu-py313-cu130-ubuntu22.04-sagemaker`. This is AWS's own PyTorch image in Jakarta ([AWS: images](https://aws.github.io/deep-learning-containers/reference/available_images/), [registry per region](https://aws.github.io/deep-learning-containers/reference/region_availability/)). The job only uses its Python and SageMaker's training toolkit.
   - **Input mode:** File.
4. **Resource configuration:**
   - **Instance type:** `ml.g5.2xlarge`. **Instance count:** 1.
   - **Additional storage volume per instance (GB):** `100`.
5. **Network:** leave the defaults. If your company requires a VPC, it needs a NAT gateway for internet access (Phase 0).
6. **Stopping condition:** **Maximum runtime** of 2 days (`172800` seconds).
7. **Managed spot training:** leave it **off**. The job runs on demand.
8. **Checkpoint configuration:**
   - **S3 location:** `s3://<bucket>/metamorph-step9/checkpoints/`.
   - **Local path:** `/opt/ml/checkpoints`.
9. **Hyperparameters,** to tell AWS's image which script to run. Choose **Add hyperparameter** three times. Enter the values with the double quotes, as SageMaker's own SDK writes them:

   | Key | Value |
   |---|---|
   | `sagemaker_program` | `"train_entry.py"` |
   | `sagemaker_submit_directory` | `"s3://<bucket>/metamorph-step9/code/sagemaker-code.tar.gz"` |
   | `sagemaker_region` | `"ap-southeast-3"` |
10. **Environment variables** (optional): `RUN_ID` = `step9`, and `MINERU_CONCURRENCY` = `1` (or `2`, if the go / no-go was faster with it).
11. **Input data configuration:**
    - **Channel name:** `inputs`.
    - **Data source:** S3. **S3 data type:** S3Prefix. **S3 data distribution type:** FullyReplicated.
    - **S3 location:** `s3://<bucket>/metamorph-step9/inputs/`.
12. **Output data configuration:** **S3 output path** `s3://<bucket>/metamorph-step9/output/`.
13. Choose **Create training job**.

### B. From a Studio terminal

[`docker/sagemaker/launch_job.py`](../docker/sagemaker/launch_job.py) makes the same call with boto3. In the `metamorph-files` space (start it again; it's the cheap one):

```bash
aws s3 cp "s3://$BUCKET/metamorph-step9/code/sagemaker-code.tar.gz" - | tar -xzf - -C ~ launch_job.py
python ~/launch_job.py --bucket "$BUCKET"
```

If it says it can't read your role from IAM, add `--role` with the ARN the console shows under **Domains → your domain → User profiles → your profile → Execution role**. Add `--concurrency 2` if the go / no-go was faster with it.

## Phase 5: watch it

| What | Where |
|---|---|
| **Status** | **Training → Training jobs → metamorph-step9-1**: **InProgress**, then **Completed**. The secondary status shows *Downloading*, *Training* and *Uploading*. |
| **Readings made so far** | In a terminal of `metamorph-files`: `aws s3 ls --recursive "s3://$BUCKET/metamorph-step9/checkpoints/" \| grep -c '\.json$'`. It grows towards 3,000 (one reading per PDF and request). |
| **Logs, as they're written** | `aws s3 cp "s3://$BUCKET/metamorph-step9/checkpoints/logs/step9.log" -`. Swap `step9.log` for `bpk.log`, `ojk.log`, `bi-website.log`, `dsn-fatwa.log` or `mineru.log`. The job page's **View logs** opens the same output in CloudWatch, if your access includes it. |
| **What it cost** | The job page shows **Billable time**: on demand, the whole training time. × $2.12 an hour is the job's cost. |

**When something stops it:**
- **The job fails or hits its maximum runtime:** create a new job with the same settings and a new name (`metamorph-step9-2`). The same checkpoint location means it resumes, after about 20 minutes of setup. Look first at `checkpoints/logs/step9.log` for the reason.
- **Stop it yourself** if the readings count stops growing for an hour: **Stop** on the job page. It bills until it stops.

## Phase 6: the results, back to the Mac

1. **Find the output.** When the job is **Completed**, its output is `s3://<bucket>/metamorph-step9/output/metamorph-step9-1/output/model.tar.gz`. It holds `step9-bundles.tgz` (the four connectors' bundles), `step9-mineru-cache.tgz` (every reading) and `logs/`.
2. **Bring it to your browser's downloads.** In `metamorph-files` (start it again):
   ```bash
   mkdir -p ~/results && aws s3 cp "s3://$BUCKET/metamorph-step9/output/metamorph-step9-1/output/model.tar.gz" - | tar -xzf - -C ~/results
   ls -lh ~/results
   ```
   In JupyterLab's file browser, open `results`, right-click each of `step9-bundles.tgz` and `step9-mineru-cache.tgz`, and choose **Download**. Then stop the space.
3. **On the Mac, build the scratch database** and compare it with the live one:
   ```bash
   cd ~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform
   docker/sagemaker/load-scratch.sh ~/Downloads/step9-bundles.tgz        # → metamorph_step9, with parser 6
   ```
   Then run the step 9 comparison, `metamorph_step9` against `metamorph`, on every criterion in the plan's [Validation](mineru-extraction-plan.md#validation) section.
   - **A failure in cleaning, rendering or the parser** is fixed on the Mac, then rerun without a GPU. Start a new job with `RUN_ID=step9-2`: it reuses the checkpoints, so it reads nothing again and takes about an hour.
   - **A failure that needs new readings** (a change to a frozen file) changes the cache key, so the files affected are read again.

## Phase 7: the live rollout, on the Mac

Only after every validation criterion passes. The rollout reads SageMaker's readings from each connector's cache, so it needs no GPU. A MinerU must still answer the reader's version check, and the Mac's does that.

1. **Put the readings in place,** and back up what the rollout changes:
   ```bash
   cd ~/Work/Metamorph-Sharia
   tar -xzf ~/Downloads/step9-mineru-cache.tgz                # → <repo>/data/mineru-cache/ for each connector
   docker exec metamorph-postgres-1 pg_dumpall -U metamorph | gzip > ~/metamorph-before-mineru.sql.gz
   tar -czf ~/connector-data-before-mineru.tgz --exclude='*/data/exports' --exclude='*/data/mineru-cache*' */data
   ```
2. **Start the Mac's MinerU** for the version check: `Metamorph-Knowledge-Platform/docker/mineru/run-dev.sh > ~/mineru-rollout.log 2>&1 &`.
3. **Run the rollout** against the live stack. Every reading comes from the cache, so it takes minutes:
   ```bash
   cd Metamorph-Knowledge-Platform
   docker compose --profile connectors build                  # the images carry the current code
   MINERU_URL=http://host.docker.internal:8010 docker/aws/reextract-all.sh
   grep -c "POST /v1/parse/jobs" ~/mineru-rollout.log          # expect 0: nothing was read on the Mac
   ```
   A number above 0 means that many files were read by the Mac's development model instead of SageMaker's. Find them in the rollout logs, and decide whether to re-read them on SageMaker.
4. **Make MinerU the engine:** set `METAMORPH_PDF_ENGINE=mineru` in `.env`, as the plan says for after step 9. Then unpause the ingest DAGs.

## Phase 8: clean up

1. **Spaces:** in Studio, delete `metamorph-gpu`. Delete `metamorph-files` too, once you no longer need its terminal. Spaces bill for their storage even when stopped.
2. **Training jobs** cost nothing once ended. Nothing to delete.
3. **S3:** once the rollout is done, delete the prefix, from a terminal (`aws s3 rm --recursive "s3://$BUCKET/metamorph-step9/"`) or in the S3 console if you have it. Until then, it holds the only copy of the readings outside the Mac.
4. **The bill:** with Billing access, use **Cost Explorer** filtered to SageMaker, a day later. Without it, the job's **Billable time** × $2.12 is the meter, and the administrator sees the rest.

## What can go wrong

| Risk | What happens | What to do |
|---|---|---|
| No GPU quota | The space won't start, or the job fails with `ResourceLimitExceeded` | Phase 0: request it days ahead, or ask the administrator |
| No internet from SageMaker | `pip`, `uv` or the model download fails in Phase 3 | The administrator: internet access for the domain and for training jobs (a NAT gateway for VPC-only) |
| NVIDIA driver older than 580 | The default build can't use the GPU | Nothing: `step9.sh` installs vLLM 0.19.1 (CUDA 12.8) then. Note which in the log: readings from different builds shouldn't mix in one corpus. |
| No capacity for ml.g5.2xlarge | The job fails with `CapacityError` or `InsufficientInstanceCapacity` | Start it again later, with a new name; it resumes from `checkpoints/` |
| The job hits its 2-day maximum | It stops as failed | A new job, same checkpoint location: it resumes |
| The space's disk fills | The go / no-go stops | Storage of 40 GB, or ask for a larger maximum |
| Studio's idle shutdown stops the GPU space mid-check | The check stops | Run it again: it skips what it has done |
| A connector fails in the job | Its bundle is missing from `step9-bundles.tgz` | Its log in `checkpoints/logs/`. Fix, then a new job with a new `RUN_ID`: the readings are reused. |
| Files fetched after the upload | The rollout reads them on the Mac | Phase 1: keep the DAGs paused until Phase 7; Phase 7 step 3 counts them |
