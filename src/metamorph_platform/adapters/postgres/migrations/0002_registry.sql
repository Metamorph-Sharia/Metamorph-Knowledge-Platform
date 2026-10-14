-- registry: the system of record. Written only by the loader, resolver, structure parser and validity jobs.
-- Contract vocabularies (kind, status, role, rights, relation, ...) are not repeated as CHECK constraints:
-- the loader validates every document against the contract's JSON Schema, the single definition.

CREATE SCHEMA registry;
COMMENT ON SCHEMA registry IS 'System of record: documents merged across sources, their files, texts, provisions and links.';

CREATE TABLE registry.document (
    id              text PRIMARY KEY,                  -- canonical (ojk:pojk:2014:5) or unresolved:{connector}:{key}
    issuer          text NOT NULL,
    family          text NOT NULL,
    number          text NOT NULL,
    year            integer,
    citation        text NOT NULL,
    title           text NOT NULL,
    language        text NOT NULL,
    kind            text NOT NULL,
    id_confidence   text NOT NULL,
    status          text NOT NULL,
    status_source   text NOT NULL,
    status_as_of    date,
    enacted_on      date,
    promulgated_on  date,
    effective_on    date,
    first_loaded_at timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX document_issuer_family_idx ON registry.document (issuer, family, year);

CREATE TABLE registry.document_source (
    connector         text NOT NULL,
    source_id         text NOT NULL,
    document_id       text NOT NULL REFERENCES registry.document (id),
    connector_version text NOT NULL,
    url               text NOT NULL,
    fetched_at        timestamptz NOT NULL,
    received          jsonb NOT NULL,                  -- the contract document exactly as loaded
    source_fields     jsonb NOT NULL DEFAULT '{}',
    package_hash      text NOT NULL,                   -- sha256 of the bundle line: unchanged lines are skipped
    bundle_id         bigint NOT NULL REFERENCES ingest.bundle (id),
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    missing_since     timestamptz,                     -- absent from a complete snapshot of its connector
    PRIMARY KEY (connector, source_id)
);
CREATE INDEX document_source_document_idx ON registry.document_source (document_id);

CREATE TABLE registry.alias (
    alias_key   text NOT NULL,                         -- normalized citation form, e.g. "pojk 5/pojk.05/2014"
    document_id text NOT NULL REFERENCES registry.document (id),
    origin      text NOT NULL CHECK (origin IN ('source', 'derived', 'curated')),
    PRIMARY KEY (alias_key, document_id)
);

CREATE TABLE registry.blob (
    sha256      text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    media_type  text NOT NULL,
    size_bytes  bigint NOT NULL,
    storage_key text NOT NULL,                         -- key in the object store
    stored_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE registry.document_file (
    document_id text NOT NULL REFERENCES registry.document (id),
    sha256      text NOT NULL REFERENCES registry.blob (sha256),
    connector   text NOT NULL,
    role        text NOT NULL,
    title       text,
    source_url  text,
    rights      text NOT NULL,
    pages       integer,
    PRIMARY KEY (document_id, sha256)
);

CREATE TABLE registry.text_version (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id text NOT NULL REFERENCES registry.document (id),
    sha256      text NOT NULL REFERENCES registry.blob (sha256),
    of_file     text REFERENCES registry.blob (sha256),
    connector   text NOT NULL,
    language    text NOT NULL,
    origin      text NOT NULL,
    method      text NOT NULL,
    rights      text NOT NULL,
    paged       boolean NOT NULL,
    is_current  boolean NOT NULL DEFAULT true,         -- older versions are kept, never deleted
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, sha256)
);
CREATE INDEX text_version_current_idx ON registry.text_version (document_id) WHERE is_current;

CREATE TABLE registry.provision (
    text_version_id bigint NOT NULL REFERENCES registry.text_version (id),
    address         text NOT NULL,                     -- e.g. pasal-115/ayat-1, penjelasan/pasal-115, lampiran-i/bab-ii
    document_id     text NOT NULL REFERENCES registry.document (id),
    parent_address  text,
    kind            text NOT NULL,
    label           text NOT NULL,
    heading         text,
    ordinal         integer NOT NULL,                  -- reading order within the text
    char_start      integer NOT NULL,
    char_end        integer NOT NULL,
    page_start      integer,
    page_end        integer,
    origin          text NOT NULL CHECK (origin IN ('source', 'parsed')),
    parser_version  text,
    valid_from      date,
    valid_to        date,                              -- set when a later instrument amends or revokes it
    PRIMARY KEY (text_version_id, address),
    CHECK (char_start <= char_end)
);
CREATE INDEX provision_document_idx ON registry.provision (document_id, address);

CREATE TABLE registry.link (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type          text NOT NULL,                       -- the contract's relation vocabulary
    from_document text NOT NULL REFERENCES registry.document (id),
    from_address  text,
    to_document   text NOT NULL REFERENCES registry.document (id),
    to_address    text,
    effective_on  date,
    method        text NOT NULL CHECK (method IN ('exact_id', 'alias', 'curated')),
    confidence    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX link_identity_idx ON registry.link
    (type, from_document, coalesce(from_address, ''), to_document, coalesce(to_address, ''));
CREATE INDEX link_to_idx ON registry.link (to_document);

CREATE TABLE registry.citation (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  text NOT NULL REFERENCES registry.document (id),
    connector    text NOT NULL,
    source_id    text NOT NULL,
    relation     text NOT NULL,
    target_text  text NOT NULL,
    target_id    text,                                 -- the connector's guess, when it had one
    from_address text,
    to_address   text,
    evidence     text NOT NULL,
    found_in     text NOT NULL,
    confidence   text NOT NULL,
    link_id      bigint REFERENCES registry.link (id), -- set once resolved
    created_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (connector, source_id) REFERENCES registry.document_source (connector, source_id)
);
CREATE INDEX citation_unresolved_idx ON registry.citation (document_id) WHERE link_id IS NULL;

CREATE TABLE registry.status_event (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    text NOT NULL REFERENCES registry.document (id),
    address        text,                               -- null: the whole document
    status         text NOT NULL,
    effective_from date,
    source         text NOT NULL,
    link_id        bigint REFERENCES registry.link (id),
    recorded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX status_event_document_idx ON registry.status_event (document_id, effective_from);
