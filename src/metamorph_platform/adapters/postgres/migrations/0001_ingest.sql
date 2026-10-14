-- ingest: operational state of ingestion. Written by Airflow tasks and the loader.

CREATE SCHEMA ingest;
COMMENT ON SCHEMA ingest IS 'Operational state of ingestion: runs, bundles received, quarantined documents, events.';

CREATE TABLE ingest.run (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('ingest', 'registry_build')),
    connector   text,                                  -- null for a registry build
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    counts      jsonb NOT NULL DEFAULT '{}',
    error       text
);

CREATE TABLE ingest.bundle (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connector         text NOT NULL,
    connector_version text NOT NULL,
    run_id            text NOT NULL,                   -- the connector's run, from the manifest
    uri               text NOT NULL,                   -- where the bundle was read from
    manifest          jsonb NOT NULL,
    received_at       timestamptz NOT NULL DEFAULT now(),
    loaded_at         timestamptz,
    state             text NOT NULL DEFAULT 'received' CHECK (state IN ('received', 'loaded', 'failed')),
    loaded            integer NOT NULL DEFAULT 0,      -- documents new or changed
    unchanged         integer NOT NULL DEFAULT 0,
    quarantined       integer NOT NULL DEFAULT 0,
    UNIQUE (connector, run_id)
);
COMMENT ON TABLE ingest.bundle IS 'One connector export (contract v2 bundle). Loading the same run twice is refused here.';

CREATE TABLE ingest.quarantine (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bundle_id   bigint NOT NULL REFERENCES ingest.bundle (id),
    line        integer NOT NULL,
    source_id   text,                                  -- when the line was readable enough to tell
    problems    jsonb NOT NULL,                        -- every contract rule the line breaks
    payload     text NOT NULL,                         -- the raw line, which may not even be JSON
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    UNIQUE (bundle_id, line)
);
COMMENT ON TABLE ingest.quarantine IS 'Bundle lines that broke the contract. Never loaded; listed for the curation team.';

CREATE TABLE ingest.event (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    kind        text NOT NULL,                         -- new_document, text_changed, missing_from_source, ...
    connector   text,
    source_id   text,
    document_id text,
    detail      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX event_at_idx ON ingest.event (at);
CREATE INDEX event_document_idx ON ingest.event (document_id);
