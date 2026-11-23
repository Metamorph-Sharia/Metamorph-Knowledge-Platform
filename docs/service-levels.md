# Knowledge Platform service levels

Status: provisional internal agreement. The Knowledge Platform owner provides the published catalogue to Chatbot and regulation and market publication to Retrieval. Escalate API, connector, curation and publication incidents through the Knowledge Platform owner. The named owner, backup and alert route are pending confirmation. See the [MIRA measurement and error-budget policy](../../mira-ai-chatbot/docs/MIRA_SERVICE_LEVELS.md).

## Indicators and objectives

See the [event-count SLO pilot](../../mira-ai-chatbot/docs/EVENT_COUNT_SLO_PILOT.md#knowledge-platform) for catalogue and authenticated document-read cohorts.

| SLI | Eligible unit and good outcome | Provisional SLO | Measurement source |
| --- | --- | --- | --- |
| Published catalogue availability | One valid, authenticated request to the production published regulations or facets endpoint. Good when it returns a usable response matching the catalogue contract, including an empty page for a valid query with no matches. | ≥99.5% over 28 days | Count responses by operation from API telemetry and count eligible failures at the internal load balancer. Use authenticated probes against known records. |
| Published catalogue latency | Elapsed time from receipt at the internal load balancer to completion of the eligible successful response. Show regulations and facets individually. | p95 ≤500 ms for each over 28 days | Measure from the consumer-facing load balancer and correlate application time when diagnosing misses. |
| Source collection on time | One due run per source and schedule, including due runs that fail to start. Good when a successful collection and validated export complete by the next scheduled run for that schedule. A verified unchanged source qualifies. | ≥90% per source and schedule over 90 days | Join intended schedules to scheduler and export outcomes. Inspect `metamorph health` and `ingest.health_snapshot` for load age and error signals. |
| Publication on time | One eligible data change within a successful load. Start at the committed load that first contains the eligible revision. Good when the revision or a superseding revision is in the published schema within 24 hours. | ≥90% per source over 90 days | Join load and publication events by source and revision. When a single publish incorporates multiple loads, associate it with each change it makes visible. |

Report platform publication for regulation and market data independently. A deliberate curation hold is recorded with reason and timestamps. For a held revision that is later released, start the eligible publication clock at release and retain the original load and hold times. Technical failures remain eligible when the material has cleared curation. Share the publication time and revision with Retrieval so it can start its activation and reader-freshness clocks. Follow the published schema and material corruption gate when classifying publishable changes.

## Evidence and response

The deployed API template uses `/healthz`, which avoids the database. Measure the authenticated published read path to cover the published schema and load balancer. Scheduler failures and the health check provide signals for missed or stale loads. Check the connector, bundle export and load first, then registry or market publication. For catalogue failures check the consumer route, task health and shared database.

The repo documents intended daily, weekly and monthly schedules. Verify which schedules and deployment actually supply production before starting the 90-day baseline. Confirm that an on-call notification reaches an owner for a missing run, publish backlog or catalogue outage. Retain source-level schedules, success and failure outcomes, and publication timestamps. Run a known-record probe and compare it with a successful recent publish to verify the measuring path.

[Published catalogue contract](api/published-catalogue.md) · [Published schema](published-schema.md) · [Scheduled ingestion](../README.md#run-on-a-schedule-airflow) · [Airflow jobs](../dags/README.md) · [AWS deployment plan](aws-deployment-plan.md)
