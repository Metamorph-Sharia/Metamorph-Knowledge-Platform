# Running step 9 on AWS (Jakarta)

**Date:** 2026-10-21 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Status:** guide written; nothing created on AWS yet · **Using the web console instead:** [aws-step9-console-guide.md](aws-step9-console-guide.md) · **Plan:** [mineru-extraction-plan.md](mineru-extraction-plan.md), step 9 onward

Step 9 re-extracts every PDF the four connectors hold with MinerU. On this Mac that takes 2–3 days, and its vision model is a third party's GGUF conversion with no stated license (README: Running MinerU). This guide runs that work on one rented GPU instance in AWS's Jakarta region, and then hands the results back to the Mac.

Nothing is fetched from the sources again. Each connector's data is copied to S3, and each connector runs only its offline re-extraction (`reparse`, `extract --again`, `reextract`) against that copy.

## Contents

1. [The design in one page](#the-design-in-one-page)
2. [What it costs](#what-it-costs)
3. [Phase 0: before AWS (the Mac)](#phase-0-before-aws-the-mac)
4. [Phase 1: one-time AWS setup](#phase-1-one-time-aws-setup)
5. [Phase 2: copy the project and data to S3](#phase-2-copy-the-project-and-data-to-s3)
6. [Phase 3: launch and prepare the instance](#phase-3-launch-and-prepare-the-instance)
7. [Phase 4: check and benchmark (the go / no-go)](#phase-4-check-and-benchmark-the-go--no-go)
8. [Phase 5: the run](#phase-5-the-run)
9. [Phase 6: results back to the Mac, and the step 9 comparison](#phase-6-results-back-to-the-mac-and-the-step-9-comparison)
10. [Phase 7: the live rollout, then teardown](#phase-7-the-live-rollout-then-teardown)
11. [What can go wrong](#what-can-go-wrong)
12. [Appendix: IAM policies](#appendix-iam-policies)

## The design in one page

```
 Mac (live stack, unchanged)            S3 bucket (ap-southeast-3)          EC2 g5.8xlarge Spot (A10G), Jakarta
 ───────────────────────────            ──────────────────────────          ───────────────────────────────────
 connector data/ (minus exports) ──►    inputs/data/<repo>/        ──►      the same workspace layout
 source tree (tarball)           ──►    inputs/source.tgz          ──►      images built here (x86_64)
 BI's own database (pg_dump)     ──►    inputs/bi.dump             ──►      compose: mineru (vLLM) · postgres ·
                                                                            objectstore · 4 connector runs
 each connector's mineru-cache   ◄──    out/mineru-cache/<repo>/   ◄──      synced every 10 min during the run
 scratch database, for the       ◄──    out/step9-database.dump    ◄──      load + build with parser 6
 step 9 comparison                      out/logs/step9/
```

**What moves:** only the GPU-bound work, which is the MinerU readings, plus the steps that turn those readings into a database that can be compared. That means re-extract, export, load and build.

**What stays on the Mac:**
- the live database, Airflow, the curation app and the API;
- the step 9 comparison, which is CPU work and needs no GPU;
- the live rollout, which reads the cached readings.

**What makes resuming cheap:** every reading is cached in each connector's `data/mineru-cache`. The cache is keyed by the PDF's sha256, the MinerU version and the request (tier and OCR mode). A run that is stopped, interrupted or re-run picks up where it left off, and the live rollout later reads the same cache instead of calling the GPU again. That is also what makes Spot safe here.

**What has been tested:**
- the production MinerU image builds for x86_64 and passes a smoke test without a GPU;
- every connector command the runner calls exists with the flags it passes;
- the tarball command produces the 17 MB source tree;
- the idle guard stops the instance on its fourth idle check;
- `start-run.sh`, in an Ubuntu 22.04 container with tmux and cron, records the run, installs one boot-resume line, and clears the run when it finishes.

Nothing has run on AWS, so the AWS commands below are written from AWS's documentation and are untested.

**What Jakarta offers.** Its accelerated instance families are G5, G5g, G7e, P5, P5e, P5en and P6-B300 ([AWS: instance types by Region](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html)). There is no G6 (L4) and no G4dn (T4).
- **G5** (one NVIDIA A10G with 24 GB on the sizes up to 16xlarge, x86_64) is the fit. The A10G supports bf16, as the production image's vLLM expects, and its memory bandwidth is about twice the L4's.
- **G5g** is ARM with a T4G, which lacks bf16, and the images are built for x86_64.
- **G7e and the P family** are 4–40 times the price.

| Choice | Why |
|---|---|
| **One EC2 instance, no managed services** | SageMaker, EKS, ECS, load balancers and NAT gateways all charge extra or bill while idle. The work is a single batch that runs once. |
| **g5.8xlarge on Spot** (1 × A10G 24 GB, 32 vCPU, 128 GiB) | In Jakarta its Spot price is about $0.51 an hour, and AWS's Spot Advisor puts its interruption rate under 5%. The cheaper-looking g5.2xlarge ($0.46) and g5.4xlarge ($0.33) Spot sizes are interrupted more than 20% of the time. The same GPU with 4× the CPU and RAM also leaves room for the four connectors, Postgres and the object store beside MinerU. |
| **Persistent Spot request, stop on interruption**, capped at $1.00 an hour | An interruption stops the instance instead of terminating it: the volume and every reading survive, and EC2 restarts it when capacity returns. Phase 5 makes the run resume on boot. The cap keeps a price spike from costing more than on-demand g5.2xlarge. |
| **Fallback: g5.2xlarge on demand**, $1.696 an hour | Only if Spot has no capacity for g5.8xlarge or g5.16xlarge. Same GPU, so the readings are the same. |
| **Jakarta (`ap-southeast-3`)** | Your region. The data stays in Indonesia, and the Session Manager tunnel in Phase 7 is close to the Mac. It is an opt-in region, already enabled on your account. |
| **Session Manager, no SSH** | No key pair and no inbound ports. The security group has no inbound rules. |
| **AWS Deep Learning Base AMI** (Ubuntu 22.04) | It ships the NVIDIA driver, Docker, the NVIDIA Container Toolkit and the SSM agent, and it supports G5. Phase 3 checks that it is published in Jakarta, and gives a fallback. |
| **The repo's own `docker/mineru/Dockerfile`** | The same pinned image as production (MinerU 4.0.12, vLLM, Apache 2.0 models baked in), so the AWS readings are the production readings. |

## What it costs

These are Jakarta prices from AWS's own price feeds, read on 2026-10-21. Spot prices move, so check them before launching (Phase 3, step 1).

| Item | Rate | Expected use | Cost |
|---|---|---|---|
| **g5.8xlarge Spot** | about $0.51 an hour (on demand: $3.426) | 15–30 hours of reading, plus about 3 hours of setup, benchmark, load and build | **$9–17** |
| Fallback: g5.2xlarge on demand | $1.696 an hour | the same hours | $31–56 |
| EBS gp3 root volume, 150 GB | $0.096 per GB-month (about $0.47 a day) | about a week, including the instance kept stopped until the rollout | about $3.50 |
| Public IPv4 | $0.005 an hour, only while running | about 20–35 hours | about $0.20 |
| S3 Standard | $0.025 per GB-month | about 6 GB in, about 3 GB out, kept for a month | about $0.25 |
| Data transfer | in: free; out to the internet: first 100 GB a month free | about 3 GB down | $0 |
| Budgets, the idle guard | free | | $0 |
| **Total** | | | **about $13–21 on Spot**, or $35–60 on the fallback. Set the budget at $60. |

For comparison: the same work in us-east-1 on a g6.2xlarge would be $20–40 on demand. Spot in Jakarta is cheaper, and needs no other region.

**Where the 15–30 hours come from.** [`scripts/ocr_census.py`](../packages/metamorph-pdf-text/scripts/ocr_census.py) asks `request_for` what each held PDF will be read with, exactly as `ExtractPdf` does, without calling MinerU. Run on 2026-10-21, it took 16 minutes on the Mac:

| Connector | Unique PDFs | Pages | In files forced to OCR (noisy text layer) | No text layer (`auto` OCRs them) |
|---|---:|---:|---:|---:|
| BI | 2,484 | 39,533 | 2,118 | 160 |
| BPK | 190 | 30,903 | 22,439 | 501 |
| OJK | 172 | 10,754 | 193 | 7 |
| DSN-MUI | 164 | 1,355 | 1,355 | 0 |
| **All** | **3,010** (1.8 GB) | **82,545** | **26,105** | **668** |

That makes 26,773 pages read from their images and 55,772 read from their characters.

- **On the Mac,** born-digital pages read at 86 pages a minute and OCR'd pages at 7.7–12. That is about 11 hours plus 37–58 hours, so **2–3 days**.
- **On the A10G,** no MinerU figure has been published. The one public number is about 2.2 pages a second for the official MinerU2.5-Pro with vLLM on an A100 ([source](https://friendli.ai/models/aijiag/MinerU2.5-Pro-2605-0.6B)). An A10G is a fraction of an A100, so the guide assumes 20–45 OCR'd pages a minute and 100–170 born-digital. That gives 15–30 hours.
- **Phase 4 measures the real rate in its first hour,** and the decision to continue is made then.

**Guardrails, all free:**
1. **An AWS Budget** of $60 a month, alerting at 50%, 80% and 100% (Phase 1).
2. **The idle guard,** [`docker/aws/idle-stop.sh`](../docker/aws/idle-stop.sh), run by cron every 15 minutes. It stops the instance after an hour with a load average under 0.2, so a finished or stuck run stops billing. It works on Spot and on demand alike (Phase 3).
3. **The runner stops the instance itself** when it finishes (`STOP_WHEN_DONE=1`, the default).
4. **The Spot price cap** of $1.00 an hour.
5. **Stopping is not deleting:** the volume and every reading stay on disk and in S3. Only Phase 7's teardown deletes anything.

**The biggest risk is forgetting a running instance:** about $12 a day on Spot, or $41 a day for the on-demand fallback.

## Phase 0: before AWS (the Mac)

Do these first. None of them costs anything.

1. **Request the GPU quota now; it is the likeliest blocker.**
   - New accounts have 0 vCPUs for G instances, and approval takes hours to days.
   - Quotas count vCPUs, and a g5.8xlarge has 32. In the Service Quotas console (EC2, Asia Pacific (Jakarta)), request:
     - **32 vCPUs** of *All G and VT Spot Instance Requests*, quota code `L-3819A6DF`, for the Spot instance;
     - **8 vCPUs** of *Running On-Demand G and VT instances*, quota code `L-DB2E81BA`, for the g5.2xlarge fallback.
   ```bash
   aws service-quotas request-service-quota-increase --region ap-southeast-3 \
       --service-code ec2 --quota-code L-3819A6DF --desired-value 32
   aws service-quotas request-service-quota-increase --region ap-southeast-3 \
       --service-code ec2 --quota-code L-DB2E81BA --desired-value 8
   ```
2. **Install the tools:** the AWS CLI v2 and the Session Manager plugin.
   ```bash
   brew install awscli
   brew install --cask session-manager-plugin
   aws configure sso      # or: aws configure, with an IAM user's access key (Appendix: the operator policy)
   aws configure set region ap-southeast-3
   aws sts get-caller-identity
   ```
3. **Optional: give Claude Code the AWS tools**, now that credentials exist. These are the AWS MCP servers from the `aws-mcp-setup` skill: the full server needs credentials; the documentation server needs none. The MCP endpoint itself is in us-east-1; the region it acts in is Jakarta. Add to `.mcp.json` and restart:
   ```json
   {"mcpServers": {
     "aws-mcp": {"command": "uvx", "args": ["mcp-proxy-for-aws@latest", "https://aws-mcp.us-east-1.api.aws/mcp",
                                            "--metadata", "AWS_REGION=ap-southeast-3"]},
     "awsdocs": {"type": "http", "url": "https://knowledge-mcp.global.api.aws"}
   }}
   ```
4. **Freeze the code the cache key depends on until Phase 7 is done.** A change to any of these turns every cached reading into a miss, and that means a second paid run:
   - `metamorph-pdf-text`'s `MINERU_VERSION` and `TRANSLATION` (`adapters/mineru_reader.py`), and `adapters/mineru_layout.py`;
   - `application/policy.py` (`FORCED_OCR_SHARE`), `domain/quality.py` and `adapters/vocabulary.txt`, which decide each file's tier and OCR mode.

   Fixes to cleaning, rendering, alignment and the parser are safe: they reuse the cache.
5. **Keep a record of the code.** All six repositories have uncommitted work on `pdf-printed-lines` (the curation web app on `reader-layout`). The tarball in Phase 2 carries the working trees as they are. Committing first means the AWS run maps to commits; this guide doesn't require it.
6. **Never let the Mac's MinerU write a connector cache.** The cache key doesn't record which backend read a page, and the Mac's GGUF readings must not mix with the A10G's. Today no connector has a `data/mineru-cache`. Keep it that way: don't run a connector with `METAMORPH_PDF_ENGINE=mineru` on the Mac before Phase 7.

## Phase 1: one-time AWS setup

Throughout: `export AWS_REGION=ap-southeast-3 ACCOUNT=$(aws sts get-caller-identity --query Account --output text) BUCKET=metamorph-step9-$ACCOUNT`.

1. **The bucket, in Jakarta.** New buckets block public access and encrypt with SSE-S3 by default. The lifecycle rule deletes everything after 60 days, so nothing lingers on the bill:
   ```bash
   aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint=ap-southeast-3
   aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
     '{"Rules":[{"ID":"expire","Status":"Enabled","Filter":{},"Expiration":{"Days":60},
                 "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":2}}]}'
   ```
2. **The instance's role,** allowed to use this bucket and Session Manager, and nothing else. IAM is global. `instance-policy.json` is in the [Appendix](#appendix-iam-policies).
   ```bash
   aws iam create-role --role-name metamorph-step9 --assume-role-policy-document \
     '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
   aws iam put-role-policy --role-name metamorph-step9 --policy-name bucket --policy-document file://instance-policy.json
   aws iam attach-role-policy --role-name metamorph-step9 --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
   aws iam create-instance-profile --instance-profile-name metamorph-step9
   aws iam add-role-to-instance-profile --instance-profile-name metamorph-step9 --role-name metamorph-step9
   ```
3. **A security group with no inbound rules,** in the default VPC. Its outbound access is for image builds and Hugging Face downloads:
   ```bash
   VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
   SG=$(aws ec2 create-security-group --group-name metamorph-step9 --description "no inbound" --vpc-id "$VPC" \
          --query GroupId --output text)
   ```
4. **The budget,** with alerts by email at 50%, 80% and 100% of $60. Budgets are global:
   ```bash
   EMAIL=you@example.com
   python3 -c "import json; print(json.dumps([{'Notification': {'NotificationType': 'ACTUAL', 'ComparisonOperator': 'GREATER_THAN', 'Threshold': t}, 'Subscribers': [{'SubscriptionType': 'EMAIL', 'Address': '$EMAIL'}]} for t in (50, 80, 100)]))" > budget-alerts.json
   aws budgets create-budget --account-id "$ACCOUNT" \
     --budget '{"BudgetName":"metamorph-step9","BudgetLimit":{"Amount":"60","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
     --notifications-with-subscribers file://budget-alerts.json
   ```

## Phase 2: copy the project and data to S3

About 6 GB goes up, and uploads to AWS are free. [`docker/aws/stage-upload.sh`](../docker/aws/stage-upload.sh) puts everything in one folder first. It needs the compose stack up, for BI's database.

```bash
docker/aws/stage-upload.sh                                   # → ~/metamorph-step9-upload
aws s3 cp --recursive ~/metamorph-step9-upload "s3://$BUCKET/inputs/"
```

| File | What it is |
|---|---|
| `source.tgz` | The workspace's repositories as they are, uncommitted work included, in about 17 MB. Leaves out `data/`, `.env` files (your secrets), virtualenvs, `node_modules` and the EDA folder. |
| `source-revisions.txt` | Each repository's commit, and how many files differ from it |
| `data-<repo>.tgz` × 4 | Each connector's `data/` without its old bundles. `exports/` is 10.6 GB of the 14.7 GB and isn't needed, since step 9 exports fresh bundles. BI 0.8 GB, BPK 2.1 GB, OJK 0.65 GB, DSN-MUI 0.64 GB. |
| `bi.dump` | BI's own database (13 MB), which its `reextract` also updates |

The live database is not uploaded. The comparison in Phase 6 runs on the Mac, beside it.

## Phase 3: launch and prepare the instance

1. **Check the Spot prices and the AMI.**
   ```bash
   aws ec2 describe-spot-price-history --instance-types g5.8xlarge g5.16xlarge g5.2xlarge \
       --product-descriptions Linux/UNIX --start-time "$(date -u +%FT%TZ)" \
       --query 'SpotPriceHistory[].[InstanceType,AvailabilityZone,SpotPrice]' --output table
   AMI=$(aws ssm get-parameter --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id \
           --query Parameter.Value --output text) && echo "$AMI"
   ```
   - **Prices:** g5.8xlarge should be around $0.51. If it is above $1.00, the cap would refuse it, so use g5.16xlarge (also one A10G, interrupted under 5% of the time, about $0.57) or the on-demand fallback.
   - **AMI:** if `get-parameter` says the parameter isn't found, the Deep Learning AMI isn't published in Jakarta. Use plain Ubuntu 22.04 and [the fallback in step 5](#no-deep-learning-ami-in-jakarta).
2. **Launch the Spot instance.** The request is persistent: on interruption it stops instead of terminating. If it fails with `InsufficientInstanceCapacity`, add `--subnet-id` with another default subnet (another Availability Zone), or change the type to g5.16xlarge.
   ```bash
   ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type g5.8xlarge \
          --instance-market-options 'MarketType=spot,SpotOptions={MaxPrice=1.00,SpotInstanceType=persistent,InstanceInterruptionBehavior=stop}' \
          --iam-instance-profile Name=metamorph-step9 --security-group-ids "$SG" \
          --metadata-options HttpTokens=required \
          --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=150,VolumeType=gp3,DeleteOnTermination=true}' \
          --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=metamorph-step9}]' \
                               'ResourceType=volume,Tags=[{Key=Name,Value=metamorph-step9}]' \
                               'ResourceType=spot-instances-request,Tags=[{Key=Name,Value=metamorph-step9}]' \
          --query 'Instances[0].InstanceId' --output text)
   ```
   **The on-demand fallback** is the same command with `--instance-type g5.2xlarge` and without `--instance-market-options`.
3. **Open a shell.** There is no SSH: the session runs as `ssm-user`, so switch to `ubuntu` (uid 1000, the connectors' container user) before touching any file.
   ```bash
   aws ssm start-session --target "$ID"
   sudo -iu ubuntu
   ```
4. **Prepare the instance:** unpack the source, then let [`docker/aws/instance-setup.sh`](../docker/aws/instance-setup.sh) do the rest. Run as `ubuntu`, on the instance:
   ```bash
   export BUCKET=metamorph-step9-<account>
   mkdir -p ~/work && cd ~/work
   aws s3 cp "s3://$BUCKET/inputs/source.tgz" - | tar -xzf -
   cd Metamorph-Sharia/Metamorph-Knowledge-Platform
   docker/aws/instance-setup.sh                 # 30–60 minutes, mostly building the 19.6 GB MinerU image
   ```
   It checks the GPU driver, unpacks each connector's data, and writes a `.env` with a new MinerU API key. It installs the idle guard, builds the images (MinerU, the four connectors, the platform), starts Postgres, the object store and MinerU, and restores BI's database.

   Running it again skips what is already done. From here on, the idle guard stops the instance after an hour with nothing to do, including while you are away between phases. Start it again to continue.
5. <a name="no-deep-learning-ami-in-jakarta"></a>**Only if the Deep Learning AMI isn't in Jakarta:** launch with Canonical's Ubuntu 22.04 instead, then install the driver, Docker and the NVIDIA Container Toolkit before step 4.
   - **The AMI:**
     ```bash
     AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id \
             --query Parameter.Value --output text)
     ```
   - **On the instance:** the image's CUDA 13.0 needs driver 580 or newer. Ubuntu's AMIs include the SSM agent.
     ```bash
     sudo apt-get update && sudo apt-get install -y ubuntu-drivers-common
     sudo ubuntu-drivers install --gpgpu nvidia:580-server
     curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu
     curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
     curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
       | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' \
       | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
     sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
     sudo nvidia-ctk runtime configure --runtime=docker && sudo reboot
     ```

## Phase 4: check and benchmark (the go / no-go)

This is the first billed hour. [`docker/aws/benchmark.sh`](../docker/aws/benchmark.sh) runs `mineru_check.py` against the instance's MinerU, from a connector image, because those images hold `metamorph_pdf_text`:

```bash
docker/aws/benchmark.sh
```

It times a 50-page scan and a 43-page born-digital regulation from BPK, the same ones timed on the Mac in step 8.

**Go when:**
- the check prints `version`, `tiers` and four `models` lines, and exits 0;
- the scan reads at 20 pages a minute or more: its line `timed standard auto → ocr … 50 pages` shows **150 s or less**.

**Then work out the cost:**
- **The two rates:** the scan rate is 3,000 ÷ the scan's seconds, in pages a minute. The born-digital rate is 2,580 ÷ the seconds on `timed standard auto → txt … 43 pages`. The `rate` lines average both files together, so don't use them for this.
- **The hours:** OCR'd pages take 26,773 ÷ the scan rate minutes, and born-digital pages 55,772 ÷ the born-digital rate. Rerun the census on the Mac first if files were added since 2026-10-21. If that gives more than 35 hours, stop and reconsider before going on.

**Optionally, try `MINERU_CONCURRENCY=2`** in `.env`, then `docker compose --profile mineru up -d mineru`, and rerun. Keep it if the scan rate rises; the four connectors queue jobs side by side, and the g5.8xlarge has the CPU for it.

## Phase 5: the run

```bash
BUCKET=metamorph-step9-<account> docker/aws/start-run.sh
tmux attach -t step9                         # to watch; Ctrl-b d leaves it running
```

[`docker/aws/start-run.sh`](../docker/aws/start-run.sh) starts the run in a detached `tmux` session, so closing the session doesn't stop it. It also records the run as pending and adds an `@reboot` cron line.
- **Why:** after a Spot interruption, EC2 restarts the instance when capacity returns, and only EC2 can ([AWS: interruption behavior](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/interruption-behavior.html)). At boot the line starts the run again from the cache.
- **When it ends:** a finished run clears its pending mark, so later boots do nothing.

**What [`docker/aws/reextract-all.sh`](../docker/aws/reextract-all.sh) does:**
1. Runs the four connectors in parallel, each in its own image with its data mounted, exactly as Airflow would:

   | Connector | Command |
   |---|---|
   | OJK | `ojk-connector reparse`, then `export --format v2` |
   | BPK | `bpk-connector extract --again`, then `export --format v2` |
   | BI | `python -m src.cli reextract`, then `src.pipeline.exporter_v2` |
   | DSN-MUI | `scripts/reextract.py`, then `dsn export` |

   None of these fetches from the sources.
2. Copies MinerU's readings to `s3://$BUCKET/out/mineru-cache/<repo>/` every 10 minutes.
3. Loads every bundle whose connector didn't fail into the instance's database, then runs `metamorph build`, which parses with parser 6 and publishes, and `metamorph health`.
4. Uploads a dump of that database, `out/step9-database.dump`, and the readings and logs as one file each: `out/step9-mineru-cache.tgz` and `out/step9-logs.tgz`. Then the instance stops itself.

**Watch it:**
- **Progress:** `tail -f ~/work/reextract-logs/step9/*.log`, and `nvidia-smi` for GPU use.
- **Money:** Cost Explorer runs a day behind. The instance's running hours × the Spot price is the honest meter.
- **Interruptions:** `aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].[State.Name,StateReason.Message]'` from the Mac.

**When something stops it:**
- **A Spot interruption:** nothing to do. EC2 restarts the instance, and `start-run.sh` resumes the run from `data/mineru-cache`. An interruption during the load step can leave a run id half loaded; the loader then refuses that bundle, and the log says so. Rerun with a new `RUN_ID` (Phase 6).
- **The idle guard or a crash:** start the instance (`aws ec2 start-instances --instance-ids "$ID"`). `start-run.sh` resumes the run at boot.
- **A connector that failed** logs why in `reextract-logs/step9/<bundle>.log`, and the others are still loaded.

## Phase 6: results back to the Mac, and the step 9 comparison

The instance stopped itself at the end of Phase 5. Keep it stopped, not terminated: only its volume is billed (about $0.47 a day), and Phase 7 may need it again.

1. **Restore the scratch database beside the live one.** It is the state after re-extraction, load and parser 6.
   ```bash
   docker exec metamorph-postgres-1 createdb -U metamorph metamorph_step9
   aws s3 cp "s3://$BUCKET/out/step9-database.dump" - | docker exec -i metamorph-postgres-1 pg_restore -U metamorph -d metamorph_step9 --no-owner
   mkdir -p ../Metamorph-EDA/2026-10-2x-mineru-extraction/logs
   aws s3 cp "s3://$BUCKET/out/step9-logs.tgz" - | tar -xzf - -C ../Metamorph-EDA/2026-10-2x-mineru-extraction/logs
   ```
2. **Run the step 9 comparison** (the plan's EDA harness, in `Metamorph-EDA/2026-10-2x-mineru-extraction/`), `metamorph_step9` against `metamorph`, against every criterion in the plan's [Validation](mineru-extraction-plan.md#validation) section.
   - **A failure in cleaning, rendering, alignment or the parser** is fixed and tested on the Mac, then re-checked on the instance, where every reading is now a cache hit. That takes about an hour of instance time, not a GPU run:
     1. Upload the changed source again (Phase 2 step 3) and unpack it on the instance over `~/work`. The connectors' `data/` is not in the tarball, so it stays.
     2. Rebuild the images that changed. A change in `metamorph-pdf-text` means the four connector images.
     3. Run Phase 5 again with a new run id: `RUN_ID=step9-2 BUCKET=... docker/aws/start-run.sh`. The loader refuses a run id it has already loaded.
     4. Restore `out/step9-2-database.dump` and compare again.
   - **A failure that needs new readings** (a change to a frozen file, Phase 0 step 4) changes the cache key, so the affected files are read by the GPU again in that same rerun.
   - Don't rerun with `METAMORPH_PDF_ENGINE=mineru` on the Mac before Phase 7: it would write into the live connector stores.

## Phase 7: the live rollout, then teardown

Only after every validation criterion passes.

1. **Bring the readings down into each connector's own cache,** from the workspace root. The archive holds `<repo>/data/mineru-cache/…` for each connector. Use the latest run's file:
   ```bash
   aws s3 cp "s3://$BUCKET/out/step9-mineru-cache.tgz" - | tar -xzf -
   ```
2. **Back up what the rollout changes:** the live database and the connectors' stores.
   ```bash
   docker exec metamorph-postgres-1 pg_dumpall -U metamorph | gzip > ~/metamorph-before-mineru.sql.gz
   tar -czf ~/connector-data-before-mineru.tgz --exclude='*/data/exports' --exclude='*/data/mineru-cache' */data
   ```
3. **Point the Mac at the A10G, so the instance reads any miss** (a file added since Phase 2) and the corpus stays all-A10G.
   1. Start the instance: `aws ec2 start-instances --instance-ids "$ID"`. The resume line does nothing now, because the finished run cleared its pending mark.
   2. In a session on it, as `ubuntu` in `~/work/Metamorph-Sharia/Metamorph-Knowledge-Platform`, run `docker compose --profile mineru up -d mineru`. It publishes port 8010 on the instance's loopback only.
   3. On the Mac, open the tunnel and leave it open:
      ```bash
      aws ssm start-session --target "$ID" --document-name AWS-StartPortForwardingSession \
          --parameters '{"portNumber":["8010"],"localPortNumber":["8011"]}'
      ```
   4. Copy the instance's `METAMORPH_MINERU_API_KEY` into the Mac's `.env`. Leave the Mac's own MinerU stopped.
   5. Check through the tunnel: `METAMORPH_MINERU_API_KEY=<the key> uv run python packages/metamorph-pdf-text/scripts/mineru_check.py --url http://127.0.0.1:8011`. Containers reach the same tunnel as `host.docker.internal:8011`.

   The idle guard still runs, so the instance stops itself an hour after the rollout is done.
4. **Run the rollout** against the live stack: the same script, without `BUCKET`. The connectors find their readings in `data/mineru-cache`, so this takes minutes, not hours.
   ```bash
   cd Metamorph-Knowledge-Platform
   MINERU_URL=http://host.docker.internal:8011 docker/aws/reextract-all.sh
   ```
   Then set `METAMORPH_PDF_ENGINE=mineru` in `.env`, as the plan says for after step 9.
5. **Tear down.** Cancel the Spot request first: a persistent request would otherwise launch a new instance.
   ```bash
   SIR=$(aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].SpotInstanceRequestId' --output text)
   [ "$SIR" != None ] && aws ec2 cancel-spot-instance-requests --spot-instance-request-ids "$SIR"
   aws ec2 terminate-instances --instance-ids "$ID"                 # also deletes its volume
   aws ec2 describe-volumes --filters Name=tag:Name,Values=metamorph-step9 --query 'Volumes[].VolumeId'      # expect []
   aws ec2 describe-spot-instance-requests --filters Name=state,Values=open,active --query 'SpotInstanceRequests[].SpotInstanceRequestId'  # expect []
   ```
   Keep the bucket until the 60-day lifecycle rule empties it. The readings in it are the only copy outside the Mac, and rebuilding them would mean paying for the GPU again.
6. **Check the bill a day later** in Cost Explorer, grouped by service. Expect EC2 compute, EBS and S3, and nothing else.

**Still open after rollout:** new documents ingested after this need a MinerU service. One option is to start the instance for each batch with the tunnel from step 3. The other is the Mac's own MinerU, but its vision model is the unlicensed GGUF conversion, for development only. This is the plan's open decision, not part of step 9.

## What can go wrong

| Risk | What happens | What to do |
|---|---|---|
| No GPU quota | `run-instances` fails with `MaxSpotInstanceCountExceeded` or `VcpuLimitExceeded` | Phase 0 step 1, days ahead: 32 Spot vCPUs |
| No Spot capacity for g5.8xlarge | `InsufficientInstanceCapacity` | Another Availability Zone (`--subnet-id`), then g5.16xlarge Spot, then g5.2xlarge on demand |
| A Spot interruption | The instance stops; the run's containers die | Nothing: EC2 restarts it, and the `@reboot` line resumes from the cache (Phase 5) |
| No Deep Learning AMI in Jakarta | `get-parameter` finds no parameter | The plain Ubuntu fallback, Phase 3 step 5 |
| The MinerU image fails to start on the GPU | It was built for amd64 and smoke-tested on the Mac on 2026-10-21 (vLLM 0.28.0, torch 2.13 for CUDA 13.0, the production models `ok`, runs as `mineru`), but it has never run on an NVIDIA GPU | Allow an hour in Phase 3. CUDA 13.0 needs NVIDIA driver 580 or newer. |
| The A10G is slower than assumed | The cost rises in proportion | Phase 4 decides before the long run. Above 35 hours on Spot it still costs under $20, so the question is time, not money. |
| An instance left running | about $12 a day on Spot, $41 on demand | The runner stops it; the idle guard stops it; the budget emails |
| The cache is invalidated by a code change | Every file is a miss | Phase 0 step 4: freeze those files until Phase 7 |
| The Mac's GGUF readings mix into the caches | Readings from two backends in one corpus | Phase 0 step 6; Phase 7 step 3 sends misses to the A10G |
| A secret ends up in S3 | | `.env` files are excluded from the tarball. The instance's API key is generated on the instance. The bucket is private. |

## Appendix: IAM policies

**`instance-policy.json`**, for the instance's role. Replace `BUCKET`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::BUCKET"},
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
     "Resource": "arn:aws:s3:::BUCKET/*"}
  ]
}
```

**The operator policy**, for the person running this guide from the Mac, when not using an administrator. These are the actions the guide calls:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": [
      "ec2:RunInstances", "ec2:StartInstances", "ec2:StopInstances", "ec2:TerminateInstances", "ec2:CreateTags",
      "ec2:Describe*", "ec2:CreateSecurityGroup", "ec2:RequestSpotInstances", "ec2:CancelSpotInstanceRequests",
      "ssm:StartSession", "ssm:TerminateSession", "ssm:GetParameter",
      "budgets:*", "servicequotas:*", "ce:GetCostAndUsage",
      "iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:CreateInstanceProfile",
      "iam:AddRoleToInstanceProfile", "iam:PassRole", "iam:GetRole", "iam:GetInstanceProfile",
      "iam:CreateServiceLinkedRole"],
     "Resource": "*"},
    {"Effect": "Allow", "Action": "s3:*",
     "Resource": ["arn:aws:s3:::metamorph-step9-*", "arn:aws:s3:::metamorph-step9-*/*"]}
  ]
}
```

`iam:CreateServiceLinkedRole` lets EC2 create its Spot service-linked role on the first Spot launch in the account.
