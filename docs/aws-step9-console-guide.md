# Running step 9 on AWS with the web console (Jakarta)

**Date:** 2026-10-21 · **Region:** Asia Pacific (Jakarta), `ap-southeast-3` · **Status:** guide written; nothing created on AWS yet · **With SageMaker AI only:** [aws-step9-sagemaker-guide.md](aws-step9-sagemaker-guide.md) · **Command-line version, design and costs:** [aws-step9-guide.md](aws-step9-guide.md)

This is the same plan as [aws-step9-guide.md](aws-step9-guide.md), done through the AWS Management Console instead of the AWS CLI:
- **One rented GPU instance** (g5.8xlarge on Spot, one NVIDIA A10G) runs MinerU and the four connectors' offline re-extraction, export, load and build.
- **The results come back to the Mac,** which runs the comparison and the live rollout.
- **Nothing is fetched from the sources again.**

The reasons for each choice, the full cost table and the risks are in that guide. This one covers how to do each step in the console.

**Expected cost:** about $13–21 on Spot, or $35–60 if you fall back to on-demand g5.2xlarge.

## What still needs a terminal

The console configures AWS. These steps still need typed commands:

| Where | What | Why the console can't |
|---|---|---|
| **The Mac's Terminal** | `docker/aws/stage-upload.sh`, which puts everything to upload in one folder; restoring the results; the rollout | They read and change files and databases on the Mac |
| **The instance, in the browser** | Three scripts: setup, benchmark, start the run | The console opens a terminal on the instance in a browser tab (Session Manager). No SSH or key pair is needed. |
| **The Mac, only for the rollout tunnel** | One `aws ssm start-session` command | Port forwarding to the instance is CLI-only. Phase 7 has a console-only alternative. |

The instance-side work is in short scripts in `docker/aws/`, so very little has to be pasted into the browser terminal.

**Console labels change over time.** If a button has moved, the setting's name is the thing to search for. Every screen below assumes the region selector (top right of the console) shows **Asia Pacific (Jakarta)**. S3, IAM, Budgets and Billing ignore it, because they are global or ask for the region themselves.

## Contents

1. [Phase 0: before you start](#phase-0-before-you-start)
2. [Phase 1: Service Quotas (request the GPU)](#phase-1-service-quotas-request-the-gpu)
3. [Phase 2: Budgets (the cost alarm)](#phase-2-budgets-the-cost-alarm)
4. [Phase 3: S3 (the bucket)](#phase-3-s3-the-bucket)
5. [Phase 4: IAM (the instance's role)](#phase-4-iam-the-instances-role)
6. [Phase 5: EC2 security group](#phase-5-ec2-security-group)
7. [Phase 6: upload the project and data](#phase-6-upload-the-project-and-data)
8. [Phase 7: EC2, launch the Spot instance](#phase-7-ec2-launch-the-spot-instance)
9. [Phase 8: connect and set the instance up](#phase-8-connect-and-set-the-instance-up)
10. [Phase 9: benchmark (go / no-go)](#phase-9-benchmark-go--no-go)
11. [Phase 10: the run](#phase-10-the-run)
12. [Phase 11: download the results; the step 9 comparison](#phase-11-download-the-results-the-step-9-comparison)
13. [Phase 12: the live rollout](#phase-12-the-live-rollout)
14. [Phase 13: teardown and the bill](#phase-13-teardown-and-the-bill)
15. [Everyday console tasks](#everyday-console-tasks)

## Phase 0: before you start

1. **Sign in** to the console with a user that can create IAM roles, S3 buckets, EC2 instances and budgets. An administrator works. For a narrower user, the operator policy is in [the other guide's appendix](aws-step9-guide.md#appendix-iam-policies).
2. **Note your account ID:** click your account name (top right). Copy the 12-digit **Account ID**. This guide calls it `<account-id>`.
3. **Freeze the cache-key code** until the rollout is done: [Phase 0, step 4](aws-step9-guide.md#phase-0-before-aws-the-mac) of the other guide. Changing those files would invalidate every reading and mean paying for the GPU again.
4. **Don't run a connector with `METAMORPH_PDF_ENGINE=mineru` on the Mac** until Phase 12, so the Mac's MinerU never writes a reading into the connector caches.

## Phase 1: Service Quotas (request the GPU)

New accounts can't launch GPU instances until the quota is raised. Approval takes hours to days, so do this first.

1. In the search bar at the top, type **Service Quotas** and open it. Check that the region is **Asia Pacific (Jakarta)**.
2. In the left menu, choose **AWS services**, then search for and open **Amazon Elastic Compute Cloud (Amazon EC2)**.
3. In **Search by quota name**, type `G and VT`.
4. Open **All G and VT Spot Instance Requests** (code `L-3819A6DF`).
   - Choose **Request increase at account level**.
   - In **Increase quota value**, enter `32` (a g5.8xlarge has 32 vCPUs).
   - Choose **Request**.
5. Go back and open **Running On-Demand G and VT instances** (code `L-DB2E81BA`).
   - Request `8`, for the g5.2xlarge fallback.
6. Follow both in **Quota request history** (left menu). Wait until both show **Approved**, or until AWS Support asks for a use case. If asked, reply: "One-off batch document OCR with a single A10G instance for about two days."

## Phase 2: Budgets (the cost alarm)

1. Search for **Billing and Cost Management** and open it. In the left menu, choose **Budgets**, then **Create budget**.
2. **Budget setup:** choose **Customize (advanced)**. **Budget types:** choose **Cost budget**, then **Next**.
3. **Details:**
   - **Budget name:** `metamorph-step9`.
   - **Period:** Monthly. **Budget renewal type:** Recurring budget. **Budgeting method:** Fixed.
   - **Enter your budgeted amount:** `60`.
   - **Budget scope:** All AWS services.
   - Choose **Next**.
4. **Alerts:** choose **Add an alert threshold** three times, for **50**, **80** and **100** (% of budgeted amount). Set **Trigger** to **Actual** and **Email recipients** to your email each time. Choose **Next**.
5. **Attach actions:** skip, then **Next**, then **Create budget**.

## Phase 3: S3 (the bucket)

1. Open **S3**, then **Create bucket**.
   - **AWS Region:** Asia Pacific (Jakarta) ap-southeast-3.
   - **Bucket type:** General purpose, if asked.
   - **Bucket name:** `metamorph-step9-<account-id>`.
   - **Object Ownership:** ACLs disabled (the default).
   - **Block Public Access settings:** keep **Block all public access** ticked (the default).
   - **Bucket Versioning:** Disable. **Default encryption:** SSE-S3 (the default).
   - Choose **Create bucket**.
2. **A lifecycle rule, so nothing lingers on the bill.** Open the bucket, then the **Management** tab, then **Create lifecycle rule**.
   - **Lifecycle rule name:** `expire-after-60-days`.
   - **Choose a rule scope:** **Apply to all objects in the bucket**, and tick the acknowledgement.
   - **Lifecycle rule actions:** tick **Expire current versions of objects**, and **Delete expired object delete markers or incomplete multipart uploads**.
   - **Days after object creation:** `60`. Under incomplete multipart uploads, tick **Delete incomplete multipart uploads**, with **Number of days** `2`.
   - Choose **Create rule**.
3. **Create the folder for the inputs:** in the bucket's **Objects** tab, choose **Create folder**, name it `inputs`, then **Create folder**. The instance creates `out/` itself.

## Phase 4: IAM (the instance's role)

The instance gets a role that can use this one bucket and Session Manager, and nothing else.

1. Open **IAM**. In the left menu choose **Roles**, then **Create role**.
2. **Trusted entity type:** AWS service. **Use case:** EC2 (the plain **EC2** option). Choose **Next**.
3. **Add permissions:** search for `AmazonSSMManagedInstanceCore`, tick it, then **Next**.
4. **Role name:** `metamorph-step9`. Choose **Create role**. The console also creates the instance profile EC2 needs, under the same name.
5. **Add the bucket permission.** Open the role, then the **Permissions** tab, then **Add permissions → Create inline policy**.
   - Choose **JSON**, delete what is there, and paste the policy below with your bucket name.
   - Choose **Next**, name it `step9-bucket`, then **Create policy**.

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::metamorph-step9-<account-id>"},
       {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
        "Resource": "arn:aws:s3:::metamorph-step9-<account-id>/*"}
     ]
   }
   ```

## Phase 5: EC2 security group

A firewall with no way in. The browser terminal works without inbound rules.

1. Open **EC2**. In the left menu choose **Network & Security → Security Groups**, then **Create security group**.
   - **Security group name:** `metamorph-step9`. **Description:** `no inbound`. **VPC:** the default VPC.
   - **Inbound rules:** leave empty, and delete any rule that is there.
   - **Outbound rules:** keep the default **All traffic**. The instance needs it to build images and download the models.
2. Choose **Create security group**.

## Phase 6: upload the project and data

1. **On the Mac, prepare the upload folder.** In Terminal, with the compose stack running:
   ```bash
   cd ~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform
   docker/aws/stage-upload.sh                   # writes ~/metamorph-step9-upload, about 6 GB
   ```
   It writes the following files. Nothing in them is fetched from the sources.

   | File | What it is |
   |---|---|
   | `source.tgz` | The workspace's repositories, with uncommitted work, but without `data/`, `.env`, virtualenvs or the EDA folder |
   | `source-revisions.txt` | Each repository's commit |
   | `data-BI-Source-Connector.tgz` and the three others | Each connector's `data/`, without its 10.6 GB of old `exports/` |
   | `bi.dump` | BI's own database |
2. **Upload in the S3 console.** Open the bucket, then the `inputs/` folder, then **Upload**.
   - Choose **Add files**, select all seven files in `~/metamorph-step9-upload` (Cmd-A), then **Upload**.
   - Keep the tab open until **Upload succeeded**. At 20 Mbit/s, 6 GB takes about 40 minutes. Large files are sent in parts automatically, and uploads into AWS are free.
3. **Check:** `inputs/` lists the seven files, with sizes matching `ls -lh ~/metamorph-step9-upload`.

## Phase 7: EC2, launch the Spot instance

1. **Check the Spot price first.** In **EC2**, open **Instances → Spot Requests** in the left menu, then **Pricing history**.
   - Set **Instance type** to `g5.8xlarge`, **Platform** to Linux/UNIX, and the date range to 1 day.
   - Expect about $0.51 an hour. Note the **Availability Zone** with the lowest price.
   - If g5.8xlarge is above $1.00, check `g5.16xlarge` the same way. It is also one A10G, interrupted under 5% of the time, at about $0.57.
2. Go to **Instances → Instances → Launch instances**, and fill in the form from top to bottom.
   - **Name and tags:** `metamorph-step9`.
   - **Application and OS Images:**
     - In the search box, type `Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)` and press Enter.
     - Look in the **Quickstart AMIs** tab, then in **Community AMIs**. Pick the newest one whose owner is Amazon, then **Select**.
     - It brings the NVIDIA driver, Docker, the NVIDIA Container Toolkit and the Session Manager agent.
     - If nothing is found, the AMI isn't published in Jakarta. Pick **Ubuntu Server 22.04 LTS** from **Quick Start** instead, and see [the fallback](aws-step9-guide.md#no-deep-learning-ami-in-jakarta) for the extra commands in Phase 8.
   - **Instance type:** `g5.8xlarge`.
   - **Key pair (login):** **Proceed without a key pair**. Session Manager doesn't need one.
   - **Network settings,** after choosing **Edit**:
     - **VPC:** default.
     - **Subnet:** the Availability Zone you noted, or **No preference**.
     - **Auto-assign public IP:** **Enable**. The instance needs internet access, and it has no inbound rules.
     - **Firewall:** **Select existing security group**, then `metamorph-step9`.
   - **Configure storage:** change the root volume to **150** GiB, type **gp3**.
   - **Advanced details:** open it.
     - **IAM instance profile:** `metamorph-step9`.
     - **Purchasing option:** tick **Spot instances**, then open **Customize Spot instance options**:
       - **Maximum price:** **Set your maximum price (per instance/hour)**, `1.00`;
       - **Request type:** **Persistent**;
       - **Valid to:** leave empty;
       - **Interruption behavior:** **Stop**.
     - **Metadata version:** **V2 only (token required)**.
   - **Summary:** 1 instance. Choose **Launch instance**.
3. **If it fails with "insufficient capacity",** launch again with another subnet (Availability Zone), or with `g5.16xlarge`.
4. **The on-demand fallback,** only if Spot has no capacity anywhere: the same form with **Instance type** `g5.2xlarge`, and **Purchasing option** left unticked.
5. Open **Instances**: `metamorph-step9` should reach **Running** with **2/2 checks passed** in a few minutes. **Spot Requests** shows its request as **active / fulfilled**.

## Phase 8: connect and set the instance up

1. **Open the browser terminal.** In **Instances**, tick `metamorph-step9`, choose **Connect**, then the **Session Manager** tab, then **Connect**.
   - If Connect is greyed out, wait 5 minutes for the agent to register.
   - If it still is, check that **IAM instance profile** in the instance's **Security** tab shows `metamorph-step9`.
2. **Become the `ubuntu` user.** The session starts as `ssm-user`, but the connectors' containers run as uid 1000, which is `ubuntu`. Paste with Cmd-V.
   ```bash
   sudo -iu ubuntu
   ```
3. **Unpack the source and run the setup.** Replace `<account-id>`:
   ```bash
   export BUCKET=metamorph-step9-<account-id>
   mkdir -p ~/work && cd ~/work
   aws s3 cp "s3://$BUCKET/inputs/source.tgz" - | tar -xzf -
   cd Metamorph-Sharia/Metamorph-Knowledge-Platform
   docker/aws/instance-setup.sh
   ```
   [`instance-setup.sh`](../docker/aws/instance-setup.sh) takes 30–60 minutes, mostly building the 19.6 GB MinerU image. It:
   - checks the GPU;
   - unpacks the four connectors' data;
   - writes a `.env` with a new MinerU API key;
   - installs the idle guard;
   - builds the images and starts Postgres, the object store and MinerU;
   - restores BI's database.

   It ends with **Ready**. If the browser tab closes, open a new session and run it again: it skips what is done.
4. **The idle guard is on from here.** The instance stops itself after an hour with nothing to do, including while you're away. To continue later, start it again ([Everyday console tasks](#everyday-console-tasks)).

## Phase 9: benchmark (go / no-go)

In the browser terminal (as `ubuntu`, in `~/work/Metamorph-Sharia/Metamorph-Knowledge-Platform`):

```bash
docker/aws/benchmark.sh
```

It reads a 50-page BPK scan and a 43-page born-digital BPK regulation through this instance's MinerU, the same two files timed on the Mac in step 8.

**Go when:**
- the output shows `version`, `tiers` and four `models` lines;
- the scan reads at 20 pages a minute or more: its line `timed standard auto → ocr … 50 pages` shows **150 s or less**.

**Then estimate the run:** the scan rate is 3,000 ÷ the scan's seconds, in pages a minute. The born-digital rate is 2,580 ÷ the seconds on the `timed standard auto → txt … 43 pages` line. The run takes 26,773 ÷ the scan rate plus 55,772 ÷ the born-digital rate, in minutes. (The `rate` lines average both files together, so don't use them for this.) Above 35 hours, stop and reconsider; it is cheap on Spot, so the question is time.

## Phase 10: the run

1. **Start it:**
   ```bash
   BUCKET=metamorph-step9-<account-id> docker/aws/start-run.sh
   ```
   [`start-run.sh`](../docker/aws/start-run.sh) starts the run in the background, in a `tmux` session, so closing the browser tab doesn't stop it. After a Spot interruption, EC2 restarts the instance when capacity returns, and the run resumes at boot from the readings already made.
2. **Watch it,** in a browser terminal:
   - `tmux attach -t step9` shows the run. Ctrl-b, then d, leaves it running.
   - `tail -f ~/work/reextract-logs/step9/*.log` shows each connector's log.
   - `nvidia-smi` shows the GPU's use.
3. **Watch it in the console:**
   - **EC2 → Instances → metamorph-step9 → Monitoring:** CPU stays high while it runs.
   - **S3 → the bucket → `out/mineru-cache/`:** fills every 10 minutes.
   - **EC2 → Spot Requests:** after an interruption the status reads something like `instance-stopped-no-capacity` until EC2 restarts the instance.
4. **It ends by itself.** The instance stops about 5 minutes after the run finishes. In `out/` you'll then find three files:
   - `step9-database.dump`: the scratch database after load and parser 6;
   - `step9-mineru-cache.tgz`: every MinerU reading;
   - `step9-logs.tgz`: the connectors', load and build logs.

## Phase 11: download the results; the step 9 comparison

1. **Download.** In **S3**, open the bucket, then `out/`. Tick `step9-database.dump` and choose **Download**. Do the same for `step9-mineru-cache.tgz` and `step9-logs.tgz`. The console downloads one file at a time. The first 100 GB a month out of AWS is free.
2. **Leave the instance stopped, not terminated.** Only its disk is billed while stopped, about $0.47 a day, and Phase 12 may need it.
3. **On the Mac, restore the scratch database beside the live one,** and unpack the logs:
   ```bash
   docker exec metamorph-postgres-1 createdb -U metamorph metamorph_step9
   docker exec -i metamorph-postgres-1 pg_restore -U metamorph -d metamorph_step9 --no-owner < ~/Downloads/step9-database.dump
   mkdir -p ~/Work/Metamorph-Sharia/Metamorph-EDA/2026-10-2x-mineru-extraction/logs
   tar -xzf ~/Downloads/step9-logs.tgz -C ~/Work/Metamorph-Sharia/Metamorph-EDA/2026-10-2x-mineru-extraction/logs
   ```
4. **Run the step 9 comparison,** `metamorph_step9` against `metamorph`, against the plan's [Validation](mineru-extraction-plan.md#validation) criteria. For what to do when a criterion fails, see [Phase 6 of the other guide](aws-step9-guide.md#phase-6-results-back-to-the-mac-and-the-step-9-comparison). Rerunning on the instance is cheap: every reading is cached, and the run is started the same way with `RUN_ID=step9-2`.

## Phase 12: the live rollout

Only after every validation criterion passes.

1. **Put the readings into each connector's cache,** and back up what the rollout changes. On the Mac:
   ```bash
   cd ~/Work/Metamorph-Sharia
   tar -xzf ~/Downloads/step9-mineru-cache.tgz                # → <repo>/data/mineru-cache/ for each connector
   docker exec metamorph-postgres-1 pg_dumpall -U metamorph | gzip > ~/metamorph-before-mineru.sql.gz
   tar -czf ~/connector-data-before-mineru.tgz --exclude='*/data/exports' --exclude='*/data/mineru-cache' */data
   ```
2. **Give the rollout a MinerU,** for its version check and for any file without a reading. Pick one of two options.
   - **Recommended: the instance's MinerU, through a tunnel.** Every reading then comes from the same A10G.
     - Start the instance (see [Everyday console tasks](#everyday-console-tasks)). In its browser terminal, run `cd ~/work/Metamorph-Sharia/Metamorph-Knowledge-Platform && docker compose --profile mineru up -d mineru`.
     - The tunnel itself needs the AWS CLI and the Session Manager plugin on the Mac (`brew install awscli && brew install --cask session-manager-plugin`, then `aws configure`). Follow [Phase 7, step 3 of the other guide](aws-step9-guide.md#phase-7-the-live-rollout-then-teardown).
     - Then run the rollout with `MINERU_URL=http://host.docker.internal:8011`.
   - **Console-only: the Mac's MinerU.**
     - Use this only when no connector has fetched new files since Phase 6. Keep the ingest DAGs paused from Phase 6 until now.
     - Then every PDF has a reading from AWS, and the Mac's MinerU (`docker/mineru/run-dev.sh`) only answers the version check.
     - A file that failed on AWS would be read on the Mac, so first check the logs from `step9-logs.tgz` for failed files.
     - Then run the rollout with `MINERU_URL=http://host.docker.internal:8010`.
3. **Run the rollout** against the live stack. All readings come from the cache, so this takes minutes:
   ```bash
   cd ~/Work/Metamorph-Sharia/Metamorph-Knowledge-Platform
   MINERU_URL=<from step 2> docker/aws/reextract-all.sh
   ```
   Then set `METAMORPH_PDF_ENGINE=mineru` in the Mac's `.env`, as the plan says for after step 9.

## Phase 13: teardown and the bill

1. **Cancel the Spot request and terminate the instance, in one step.** In **EC2 → Instances → Spot Requests**, tick the request for `metamorph-step9`.
   - Choose **Actions → Cancel request**.
   - In the dialog, keep **Terminate instances** ticked, then **Confirm**.
   - Cancelling matters: a persistent request would otherwise launch a new instance.
   - For the on-demand fallback, there's no request: use **Instances → Instance state → Terminate instance**.
2. **Check that nothing is left:**
   - **Instances:** `metamorph-step9` is **Terminated**.
   - **Elastic Block Store → Volumes:** no volume named `metamorph-step9`. The root volume is deleted with the instance.
   - **Spot Requests:** none **active** or **open**.
3. **Keep the bucket** until its 60-day lifecycle rule empties it. It holds the only copy of the readings outside the Mac.
   - To remove it sooner: **S3 → the bucket → Empty**, then **Delete**.
   - The IAM role and the security group cost nothing and can stay, or be deleted.
4. **Check the bill the next day.** In **Billing and Cost Management → Cost Explorer**, set the date range to this month, **Group by** to **Service**, and filter **Region** to Asia Pacific (Jakarta). Expect EC2 instances (Spot), EBS and S3, and nothing else. Your budget emails if the month passes $30.

## Everyday console tasks

| To… | Do this |
|---|---|
| Start the stopped instance (to continue, rerun or roll out) | **EC2 → Instances**, tick it, **Instance state → Start instance**. A pending run resumes by itself at boot. |
| Stop it by hand | **Instance state → Stop instance**. Its disk and every reading stay. |
| Open a terminal on it | Tick it, **Connect → Session Manager → Connect**, then `sudo -iu ubuntu` |
| See what it costs so far | **Billing and Cost Management → Cost Explorer** (a day behind), or the instance's running hours × the Spot price shown in **Spot Requests → Pricing history** |
| See whether Spot interrupted it | **EC2 → Spot Requests**: the request's **Status**, and the instance's **State** |
| Find a result file | **S3 → the bucket → `out/`** |
