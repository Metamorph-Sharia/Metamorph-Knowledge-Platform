-- Health of ingestion over time: one row per `metamorph health` (the registry_build DAG runs it after every build).

CREATE TABLE ingest.health_snapshot (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    taken_at timestamptz NOT NULL DEFAULT now(),
    status   text NOT NULL CHECK (status IN ('ok', 'warning', 'critical')),
    checks   jsonb NOT NULL                          -- [{name, severity, detail}]
);
CREATE INDEX health_snapshot_taken_idx ON ingest.health_snapshot (taken_at);
