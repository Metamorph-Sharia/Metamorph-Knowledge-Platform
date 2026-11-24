# Spec: collection on a residential host, processing on AWS

Status: ready-for-agent

Decision record: ADR 0001 (collection runs on a residential host; processing stays on AWS). Vocabulary: GLOSSARY.md (source, connector, connector job, collection, processing, collection host, bundle).

## Problem Statement

The ingestion layer was deployed on AWS on 2026-11-23, and most sources refuse it:
- OJK (JDIH, the main site and the data portal) drops the connections.
- BPK answers 403 with a bot challenge.
- BI closes the connection.
- Only DSN-MUI and BPS answer.

From a residential line in Indonesia every source answers. The sources refuse cloud addresses, including AWS Jakarta, not foreign ones. So most connector jobs cannot collect anything on AWS. The AWS `health` check stays critical for seven of the nine connectors, and the corpus that the platform, Retrieval and MIRA serve stops growing for OJK, BPK and BI.

The owner still wants the connectors managed in one place:
- each source can be enabled or disabled;
- each connector job can be triggered on its own and scheduled on its own;
- runs keep the logs and failure states that make debugging possible.

The owner does not want nine standalone scripts.

## Solution

Collection moves to a collection host on a residential line, at first the owner's Mac. Processing stays on AWS. Each side has its own Airflow, and the two are joined only by bundles in S3.

- **On the collection host,** the existing local Compose Airflow runs every connector job's collection with the Docker launcher. That is the collect step and the export of a bundle. Each run ends by uploading its bundle to S3, with a marker written last that says the bundle is complete. Jobs run on weekdays in working hours (WIB), while the laptop is awake. They use the owner's SSO session.
- **On AWS,** the deployed Airflow keeps processing. A new DAG regularly loads every complete bundle not yet loaded: oldest first within each connector, and a failure holds that connector's later bundles back. The existing chain then follows: registry build, market publish, the regulation and market indexes, and health.
- **MinerU stays on AWS's GPU.** The collection host reaches it through a CloudFront front door with MinerU's own API key. Its scheduled window moves to weekday working hours.
- **One job registry and one DAG folder** serve both Airflows. A setting tells each Airflow which side it is, and so which DAGs it loads. A connector job stays the unit that is enabled, disabled, triggered and scheduled, in the Airflow UI on the collection host.
- After a cutover gate, the AWS pieces built only for collection on AWS are retired.

## User Stories

1. As the owner, I want every connector job's collection to run on a machine on a residential line, so that the sources stop refusing it.
2. As the owner, I want one Airflow on the collection host that shows all nine connector jobs, so that I manage collection in one place instead of nine scripts.
3. As the owner, I want to disable a source by pausing its DAG, so that a source that misbehaves stops without touching the others.
4. As the owner, I want to enable a source by unpausing its DAG, so that it rejoins the schedule without a deploy.
5. As the owner, I want to trigger one connector job by hand, so that I can rerun or debug a single source.
6. As the owner, I want each connector job to keep its own schedule in the job registry, so that changing one source's cadence is a one-line change.
7. As the owner, I want to add a source by adding one connector job to the registry and its image, so that the architecture stays plug-and-play.
8. As the owner, I want collection scheduled in weekday working hours (WIB), so that it runs while my laptop is open and awake.
9. As the owner, I want a day the laptop was closed to be skipped rather than queued, so that the next run picks up where the incremental connectors left off without a pile of catch-up runs.
10. As the owner, I want the laptop to stay awake while collection runs on power, so that a run is not cut off by sleep.
11. As the owner, I want each run's bundle uploaded to S3 as the last step of its DAG, so that processing on AWS can take it from there.
12. As the owner, I want a bundle marked complete only after every one of its files is uploaded, so that a bundle half-uploaded when the laptop slept is never loaded.
13. As the owner, I want the upload to use my existing SSO session, so that no long-lived AWS key sits on my laptop.
14. As the owner, I want an upload with an expired SSO session to fail with a message telling me to sign in again, so that I know exactly what to do.
15. As the owner, I want a failed upload to be retryable without collecting again, so that one expired session does not cost a whole collection.
16. As the owner, I want connector state (SQLite stores, downloaded files) on my Mac's disk, so that the collection host's state is the authoritative one.
17. As the owner, I want the weekly backup of every connector's data to keep running, now from the collection host to the same S3 prefix, so that a lost laptop loses at most a week.
18. As the owner, I want the collection host's Airflow to be the existing local Compose stack, started without the platform API, curation web or object store, so that there is nothing new to install.
19. As the owner, I want the connector images on the collection host built locally as today, so that changing a connector needs no image registry.
20. As the owner, I want PDF-reading connector jobs to reach MinerU on AWS through a CloudFront address, so that OCR keeps the GPU's speed without a VPN or tunnel.
21. As the owner, I want MinerU's front door protected by MinerU's own API key and a rate limit, so that the GPU cannot be used by anyone who finds the address.
22. As the owner, I want MinerU's window moved to weekday working hours, so that it is up while collection runs and off the rest of the time.
23. As the owner, I want the PDF-reading jobs to start at least an hour before MinerU's window closes, so that a long read is not cut off.
24. As the owner, I want the monthly full re-reads on the first weekday of the month, with the window extended that day, so that they have the time they need.
25. As the owner, I want to start MinerU by hand outside its window with one documented command, so that I can rerun a PDF job in the afternoon.
26. As the owner, I want MinerU stopped again within an hour if I forget, so that a hand start costs at most an hour of GPU.
27. As the owner, I want AWS's Airflow to keep processing (load, registry build, market publish, the indexes, health), so that processing stays next to the database and does not depend on my laptop.
28. As the owner, I want AWS's Airflow to look for new complete bundles every 30 minutes, so that a bundle uploaded in the morning is published within the hour.
29. As the owner, I want each connector's bundles loaded oldest first, so that an incremental bundle (BPS's tables since the last success) never lands out of order.
30. As the owner, I want a bundle that fails to load to hold that connector's later bundles back, so that the registry never skips a step for that source.
31. As the owner, I want the other connectors to keep loading while one is held, so that one bad bundle does not stop the corpus.
32. As the owner, I want a bundle already loaded to be skipped, not loaded twice, so that the loading DAG can run often and safely.
33. As the owner, I want market-layer bundles (OJK register, the statistics, reports) loaded into the market layer and regulation bundles into the regulation layer, so that each lands where it did before.
34. As the owner, I want a load to fire the same Datasets as today, so that registry build, market publish and the indexes follow unchanged.
35. As the owner, I want AWS's `health` DAG to flag a connector whose bundles stop arriving, so that a closed laptop or a broken source shows up without new alerting on the Mac.
36. As the owner, I want processing failures on AWS to keep alerting through the SNS email, so that I learn of a failed load or index without opening Airflow.
37. As the owner, I want the AWS alert rule to watch only the processing task families, so that it does not name connectors that no longer run there.
38. As the owner, I want one DAG folder and one job registry for both Airflows, with a setting choosing each side's DAGs, so that a source is defined in exactly one place.
39. As the owner, I want the collection side to load only the ingest DAGs and the backup, and the processing side only the loading, build, publish, index and health DAGs, so that neither Airflow shows DAGs it cannot run.
40. As the owner, I want an Airflow started without that setting to fail with a clear message, so that a misconfigured side never runs both halves.
41. As the owner, I want `metamorph load` to read a bundle straight from S3, so that the platform owns reading bundles and no copying step is bolted on.
42. As the owner, I want the EFS copy of connector state discarded at cutover, so that there is no second copy to reconcile (DSN's three newer fatwas are already published and reload unchanged).
43. As the owner, I want a cutover gate:
    - each ingest DAG run once by hand from the Mac inside MinerU's window;
    - its bundle loaded on AWS, with registry build and the indexes following;
    - `health` passing for every enabled connector;
    - then the first scheduled weekday running on its own.

    I want this so that I know the switch works before anything is deleted.
44. As the owner, I want the connector task definitions, EFS and the connector image repositories removed only after the gate passes, so that a failed cutover can still fall back.
45. As the owner, I want BPS statistics to stay paused as it is today, so that the cutover does not change a decision made earlier.
46. As the owner, I want the deployment README to describe the two sides and the order of the cutover, so that someone else can repeat it.
47. As a future maintainer, I want the reason collection runs off AWS recorded, so that nobody moves it back without knowing the sources refuse cloud addresses.
48. As the owner, I want no new DevOps request, so that the change does not wait on another team.

## Implementation Decisions

**Two sides, one registry**
- The job registry stays the single definition of every connector job: image, schedule, collect and export commands, whether it reads PDFs, and its layer. Nothing about a source is duplicated per side.
- A new setting, `METAMORPH_SIDE`, takes `collection` or `processing`.
  - Every DAG module declares its side, and a DAG builds only when the setting matches. A missing or unknown value fails at import with a clear message.
  - Collection side: the ingest DAGs and the weekly connector-data backup.
  - Processing side: the new loading DAG, registry build, market publish, the regulation and market indexes, and health.
- The collection side runs with the Docker launcher. The processing side runs with the ECS launcher, as deployed.

**The ingest DAG on the collection side**
- The steps are discard, collect (with export), then upload. The load step moves to the processing side.
- **Upload:**
  - It copies one run's bundle to the blobs bucket (which the platform task can already read) under a key per connector and run; a lifecycle rule expires bundles after 35 days, then writes a completion marker as the last object.
  - It runs as the owner's SSO session from the Mac's AWS configuration.
  - It is idempotent: a retry re-uploads and rewrites the marker.
  - An authentication failure exits with a message telling the operator to sign in again.
- The ingest DAG no longer emits the registry Datasets. They are emitted on the processing side when a load happens.
- Schedules move to weekday working hours (WIB):
  - PDF-reading jobs start between 09:00 and 11:30 WIB;
  - the monthly full re-reads run on the first weekday of the month;
  - `catchup` stays off.
- The existing rule that a PDF-reading job starts at least 60 minutes before MinerU's window ends is kept and checked against the new window.

**Loading on the processing side**
- A new platform use case, "load pending bundles", sits behind one command: `metamorph load-pending <S3 prefix for one connector>`, with the layer chosen as `metamorph load` / `metamorph market load` choose it today.
- Its behaviour:
  - list the connector's bundles under the prefix;
  - ignore any without the completion marker;
  - skip any the ledger already records;
  - load the rest oldest first by run;
  - stop at the first failure, leaving later bundles for the next pass.
- It reports counts (loaded, skipped, held) and exits non-zero when it held a bundle, so the task fails and alerts.
- `metamorph load` and `metamorph market load` accept an S3 location as well as a directory. They download the bundle to scratch through the platform's existing S3 adapter, and record the S3 location as the bundle's URI.
- A new processing DAG, `load_bundles`, runs every 30 minutes, with one task per connector job taken from the registry. Each task runs `load-pending` for its connector in the platform image on ECS, and emits its layer's registry Dataset when it loaded something. One connector's held bundle fails only its own task.
- EFS is no longer used for bundles.

**MinerU**
- **The front door:** a CloudFront distribution with a VPC origin on the existing internal load balancer.
  - A WAF rate limit is created by script, as for the Airflow UI.
  - Access is checked by MinerU's own API key, with no edge password.
  - Requests are short because MinerU works as async jobs: submit, then poll.
- **Addresses:** the collection host's connectors are given the CloudFront address and the API key through the platform's local settings. The parameter that held the internal address for AWS connector tasks is retired with them.
- **The window:**
  - weekdays 08:45–12:45 WIB (01:45–05:45 UTC);
  - until 13:15 WIB on the first weekday of the month;
  - a stop schedule repeats hourly outside the window, so a hand start ends within an hour;
  - the hand start is one documented command.

**AWS clean-up, only after the gate**
- **Removed:** the nine connector task definitions and their task role's use; EFS and its access points; the connector image repositories; the parameters only connector tasks read; the processing-side ingest DAGs (gone through the side setting).
- **Kept:** AWS Airflow with its CloudFront UI, alerts, the mineru stack, and the platform, retrieval and ops task definitions.
- The alert rule's list of task families narrows to the processing ones.

**Unchanged**
- The connectors, the bundle contract, registry build, publish, the indexes, health's checks and the backup's S3 layout all stay as they are.

## Testing Decisions

- **What a good test is:** it checks external behaviour through the highest existing seam: what a use case does to its ports, what the job registry says as plain data, and what a template declares. It never checks internal call order. Each test is named after the behaviour, as the existing suites are.
- **Load pending bundles** is tested against in-memory ports and a fake bundle store, as LoadBundle is. Cases:
  - bundles without the marker are ignored;
  - bundles already in the ledger are skipped;
  - the order is oldest first;
  - a failure holds the later bundles and the next pass resumes from it;
  - other connectors are unaffected;
  - the report counts are right;
  - market bundles go to the market layer.

  `metamorph load` reading from S3 is tested through the same seam with the fake store. Prior art: the LoadBundle and market-bundle load tests.
- **The job registry and DAG commands** are tested as plain data, without Airflow. Cases:
  - the side setting yields each side's DAGs, and a missing value fails;
  - every ingest job ends with an upload that writes the marker last, and the command fails clearly on an authentication error;
  - the loading DAG has one task per connector job, routed to its layer and Dataset;
  - every schedule falls on weekdays in working hours, and every PDF-reading job starts at least 60 minutes before the new window ends.

  Prior art: the DAG jobs tests, including the existing MinerU-window and backup tests.
- **The templates** are parsed and checked. Cases:
  - MinerU's CloudFront distribution has a VPC origin on the internal load balancer;
  - the start and stop schedules give the weekday window, the first-weekday extension and the hourly stop;
  - the connector task definitions, EFS and the connector repositories are absent once retired;
  - the alert rule lists only processing families.

  Prior art: the ingestion-stack tests.
- **Manual:** the cutover gate is checked by hand and recorded in the README:
  - one hand run per ingest DAG from the Mac;
  - its bundle loaded on AWS;
  - health passing;
  - the first scheduled weekday.

## Out of Scope

- An always-on collection host (a Mac mini or mini PC), unattended night runs, and long-lived AWS credentials for one. The laptop is the host for now.
- Alerts raised from the collection host. AWS's health staleness check is the backstop.
- Remote access to the collection host's Airflow UI (Tailscale or a tunnel).
- Moving MinerU onto the collection host.
- Asking the regulators to allowlist AWS, or an Indonesian egress proxy.
- Any change to the connectors, the bundle contract or the platform's publish logic.
- Enabling BPS statistics.

## Further Notes

- Both sides keep `catchup` off: a closed laptop skips days, and incremental connectors catch up on the next run.
- An expired SSO session fails only the upload. The collected bundle stays on the Mac and the upload can be retried alone.
- About $115 a month for the weekday MinerU window, against about $155 for the current daily window.
- Local commits from the AWS deployment are not pushed yet: in the platform ef72dc0, eea1f95, 87053b8 and 2fdd73d, and in DSN-MUI bcec2c9. They should be pushed before this work starts on top of them.
