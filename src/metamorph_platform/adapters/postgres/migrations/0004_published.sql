-- published: the read contract for the Knowledge and Retrieval layer.
-- Effective values only: registry values with curation overrides applied, suppressed documents removed,
-- and only public or licensed content. Rebuilt per changed document; change_log says what to re-index.

CREATE SCHEMA published;
COMMENT ON SCHEMA published IS 'Read contract for the Knowledge and Retrieval layer. Never read registry or curation directly.';

CREATE TABLE published.document (
    id             text PRIMARY KEY,
    issuer         text NOT NULL,
    family         text NOT NULL,
    number         text NOT NULL,
    year           integer,
    citation       text NOT NULL,
    title          text NOT NULL,
    language       text NOT NULL,
    kind           text NOT NULL,
    id_confidence  text NOT NULL,
    status         text NOT NULL,
    status_as_of   date,
    enacted_on     date,
    promulgated_on date,
    effective_on   date,
    aliases        text[] NOT NULL DEFAULT '{}',
    curated        boolean NOT NULL DEFAULT false,     -- at least one value comes from a curation override
    published_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE published.document_source (
    document_id text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    connector   text NOT NULL,
    source_id   text NOT NULL,
    url         text NOT NULL,
    fetched_at  timestamptz NOT NULL,
    PRIMARY KEY (document_id, connector, source_id)
);

CREATE TABLE published.file (
    document_id text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    sha256      text NOT NULL,
    role        text NOT NULL,
    media_type  text NOT NULL,
    title       text,
    source_url  text,
    pages       integer,
    storage_key text NOT NULL,                         -- object-store key of the bytes
    PRIMARY KEY (document_id, sha256)
);

CREATE TABLE published.text (
    document_id text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    sha256      text NOT NULL,
    language    text NOT NULL,
    origin      text NOT NULL,
    method      text NOT NULL,
    paged       boolean NOT NULL,
    of_file     text,
    storage_key text NOT NULL,
    PRIMARY KEY (document_id, sha256)
);

CREATE TABLE published.provision (
    document_id    text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    address        text NOT NULL,
    text_sha256    text NOT NULL,
    parent_address text,
    kind           text NOT NULL,
    label          text NOT NULL,
    heading        text,
    ordinal        integer NOT NULL,
    body           text NOT NULL,                      -- the provision's text, cut from its text blob
    char_start     integer NOT NULL,
    char_end       integer NOT NULL,
    page_start     integer,
    page_end       integer,
    valid_from     date,
    valid_to       date,
    PRIMARY KEY (document_id, address)
);

CREATE TABLE published.link (
    type          text NOT NULL,
    from_document text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    from_address  text,
    to_document   text NOT NULL,                       -- may be a document not (yet) published
    to_address    text,
    effective_on  date,
    confidence    text NOT NULL
);
CREATE INDEX published_link_from_idx ON published.link (from_document);
CREATE INDEX published_link_to_idx ON published.link (to_document);

CREATE TABLE published.status_event (
    document_id    text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    address        text,
    status         text NOT NULL,
    effective_from date,
    source         text NOT NULL
);
CREATE INDEX published_status_event_idx ON published.status_event (document_id, effective_from);

CREATE TABLE published.change_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id text NOT NULL,                         -- no FK: a removal is logged after the row is gone
    change      text NOT NULL CHECK (change IN ('added', 'updated', 'removed')),
    changed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX change_log_since_idx ON published.change_log (changed_at);
