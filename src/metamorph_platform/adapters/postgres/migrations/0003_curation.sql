-- curation: what the Metamorph team decides. Overlays on the registry; source rows are never edited.

CREATE SCHEMA curation;
COMMENT ON SCHEMA curation IS 'Human decisions layered over the registry: overrides, suppressions, review queues, audit.';

CREATE TABLE curation.curator (
    username     text PRIMARY KEY,
    display_name text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE curation.override (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id text NOT NULL REFERENCES registry.document (id),
    field       text NOT NULL,                         -- e.g. "title", "status", "effective_on"
    value       jsonb NOT NULL,
    source_value jsonb,                                -- what the sources said when the override was made
    reason      text NOT NULL,
    author      text NOT NULL REFERENCES curation.curator (username),
    created_at  timestamptz NOT NULL DEFAULT now(),
    active      boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX override_active_idx ON curation.override (document_id, field) WHERE active;

CREATE TABLE curation.suppression (
    document_id text PRIMARY KEY REFERENCES registry.document (id),
    reason      text NOT NULL,
    author      text NOT NULL REFERENCES curation.curator (username),
    created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE curation.suppression IS 'Delete, as an overlay: the document stays in the registry and leaves published.';

CREATE TABLE curation.conflict (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    override_id  bigint NOT NULL REFERENCES curation.override (id),
    source_value jsonb NOT NULL,                       -- the new value a source sent under the override
    detected_at  timestamptz NOT NULL DEFAULT now(),
    state        text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'kept_override', 'accepted_source'))
);

CREATE TABLE curation.review_item (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind       text NOT NULL CHECK (kind IN (
                   'unresolved_id', 'quarantine', 'conflict', 'unresolved_citation', 'structure_suspect')),
    subject    jsonb NOT NULL,                         -- what to look at, e.g. {"document_id": "..."}
    state      text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'resolved', 'dismissed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_by text REFERENCES curation.curator (username),
    decided_at timestamptz,
    note       text
);
CREATE INDEX review_item_open_idx ON curation.review_item (kind, created_at) WHERE state = 'open';

CREATE TABLE curation.audit_log (
    id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT now(),
    author text NOT NULL REFERENCES curation.curator (username),
    action text NOT NULL,
    target jsonb NOT NULL,
    before jsonb,
    after  jsonb
);
