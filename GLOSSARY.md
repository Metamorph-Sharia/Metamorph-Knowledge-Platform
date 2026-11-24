# Metamorph Knowledge Platform

The platform turns what Indonesia's regulators publish into a curated, published corpus that the retrieval layer serves.

## Ingestion

**Source**:
A publisher's website the platform reads from, such as JDIH OJK, BPK's peraturan site or DSN-MUI's fatwa list.
_Avoid_: Data source, site, feed

**Connector**:
The program that reads one source and keeps what it read in its own store.
_Avoid_: Scraper, crawler, ingester

**Connector job**:
A connector's entry in the job registry: its image, schedule, and collect and export commands. It is the unit that is enabled, disabled, triggered and scheduled.
_Avoid_: Pipeline, task, DAG (the DAG is how Airflow shows a connector job)

**Collection**:
The part of a connector job that talks to the source: the collect step and the export of a bundle from what it collected.
_Avoid_: Scraping, crawling, sync (sync is one connector's command for it)

**Processing**:
Everything after a bundle exists: load, registry build, indexing and health.
_Avoid_: Post-processing, backend

**Collection host**:
The machine on a residential or office line where every connector job's collection runs, because sources refuse cloud addresses.
_Avoid_: Scraper box, home server, on-prem

**Bundle**:
One connector run's export in the shared contract, the hand-off from collection to processing.
_Avoid_: Dump, export file, batch
