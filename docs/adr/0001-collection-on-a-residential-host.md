---
status: accepted
---

# Collection runs on a residential host; processing stays on AWS

On 2026-11-23 OJK (jdih, ojk.go.id, data), BPK and BI refused every request from AWS Jakarta: dropped connections, a 403 bot challenge and closed connections, while the same pages answered from a residential line in Indonesia. They refuse cloud addresses, not foreign ones, so an Indonesian VPS would be refused too. We decided that collection (each connector job's collect and export) runs on a collection host on a residential line, at first the developer's Mac, under its own Airflow. Processing (load, registry build, indexing, health) stays on AWS under a second Airflow. The two are joined only by bundles in S3, each marked complete, which AWS loads in order. MinerU stays on AWS's GPU and is reached from the host through CloudFront.

## Considered Options

- **One Airflow on the host, launching processing as ECS tasks.** One UI, but every processing task would depend on the laptop being awake and signed in.
- **One Airflow on AWS with a remote worker on the host** (Celery or the Edge executor). One UI, but it needs a broker or a long-lived connection from home, and the Edge executor is experimental in Airflow 2.10.
- **Cron and scripts on the host.** Rejected because nine connectors need per-job scheduling, triggering, enabling and logs.

## Consequences

- Collection runs only when the host is awake: schedules are weekday working hours (WIB), and MinerU's window follows them.
- The jobs run as the developer's SSO session. When it expires, uploads fail until someone signs in again.
- One `dags/` folder serves both Airflows. A setting, `METAMORPH_SIDE`, picks which DAGs each one loads, so the job registry stays the single place where a source is defined.
- A dead host raises no alert of its own. AWS's health check flags the stale connectors.
