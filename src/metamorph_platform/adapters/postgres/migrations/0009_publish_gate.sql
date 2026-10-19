-- The publish gate: a curator's approval of a text's problems as they are, and the documents held back.

CREATE TABLE curation.approval (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id text NOT NULL REFERENCES registry.document (id) ON UPDATE CASCADE,
    text_sha256 text NOT NULL,
    problems    jsonb NOT NULL,                        -- exactly the problems approved: any others lapse it
    reason      text NOT NULL,
    author      text NOT NULL REFERENCES curation.curator (username),
    created_at  timestamptz NOT NULL DEFAULT now(),
    active      boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX approval_active_idx ON curation.approval (document_id, text_sha256) WHERE active;

CREATE TABLE registry.hold (
    document_id text PRIMARY KEY REFERENCES registry.document (id) ON UPDATE CASCADE ON DELETE CASCADE,
    reasons     jsonb NOT NULL,                        -- [{"check": "structure", "detail": "Pasal 3 missing"}]
    held_since  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE registry.hold IS 'Documents the publish gate holds back, and why. Rewritten by the publish step.';
