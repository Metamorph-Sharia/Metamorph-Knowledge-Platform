-- The market data layer (docs/market-data-layer-plan.md): registers of licensed entities, beside the regulation
-- layer. market holds what connectors sent under the market contract; published_market is its read contract.
-- Loads are recorded in ingest.bundle and ingest.quarantine, as contract v2 loads are.

CREATE SCHEMA market;
COMMENT ON SCHEMA market IS 'Market records as received (market contract), and the curated registers they belong to.';

-- A register is curated data: which regulations govern it, and how old its newest edition may be.
CREATE TABLE market.register (
    id          text PRIMARY KEY,                    -- {issuer}:{register}, as records name it
    issuer      text NOT NULL,
    name        text NOT NULL,
    governed_by text[] NOT NULL DEFAULT '{}',        -- regulation document IDs, curated, never inferred per entity
    fresh_days  integer NOT NULL                     -- health warns when the newest edition is older
);
INSERT INTO market.register (id, issuer, name, governed_by, fresh_days) VALUES (
    'ojk:lpbbti', 'ojk', 'Penyelenggara Layanan Pendanaan Bersama Berbasis Teknologi Informasi (fintech lending)',
    '{ojk:pojk:2024:40,ojk:seojk:2025:19}',
    90  -- OJK publishes each list one to three months after its date
);

-- One license or registration as received: the record whole, as the source of every published value.
CREATE TABLE market.entity (
    id            text PRIMARY KEY,                  -- the record's entity.id
    register      text NOT NULL REFERENCES market.register (id),
    connector     text NOT NULL,
    source_id     text NOT NULL,
    package_hash  text NOT NULL,                     -- of the record as received: unchanged records are skipped
    record        jsonb NOT NULL,
    bundle_id     bigint NOT NULL REFERENCES ingest.bundle (id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    missing_since timestamptz,                       -- the connector's snapshot no longer has it
    UNIQUE (connector, source_id)
);

-- The register editions' files, as stored in the object store.
CREATE TABLE market.file (
    sha256      text PRIMARY KEY,
    media_type  text NOT NULL,
    storage_key text NOT NULL,
    size_bytes  bigint NOT NULL
);

CREATE SCHEMA published_market;
COMMENT ON SCHEMA published_market IS
    'Read contract for market data (docs/published-market-schema.md). Rebuilt whole by each publish.';

CREATE TABLE published_market.register (
    id             text PRIMARY KEY,
    issuer         text NOT NULL,
    name           text NOT NULL,
    governed_by    text[] NOT NULL,
    newest_edition date,
    editions       integer NOT NULL,
    published_at   timestamptz NOT NULL DEFAULT now()
);

-- One edition of a register: how many it listed, and how many joined and left since the edition before.
CREATE TABLE published_market.edition (
    register    text NOT NULL REFERENCES published_market.register (id) ON DELETE CASCADE,
    edition     date NOT NULL,
    listed      integer NOT NULL,
    joined      integer NOT NULL,
    "left"      integer NOT NULL,
    sha256      text,
    source_url  text,
    storage_key text,
    PRIMARY KEY (register, edition)
);

-- A company: the records listed under the same legal name, e.g. a registration and the license that followed.
CREATE TABLE published_market.company (
    id            text PRIMARY KEY,                  -- its newest record's ID
    register      text NOT NULL REFERENCES published_market.register (id) ON DELETE CASCADE,
    legal_name    text NOT NULL,                     -- as its newest record was last listed
    names         text[] NOT NULL,                   -- every other legal and platform name listed
    business_type text NOT NULL,
    status        text NOT NULL CHECK (status IN ('licensed', 'registered', 'left')),
    first_listed  date NOT NULL,
    left_after    date                               -- the last edition that listed it, once it left
);

-- A license (KEP-…, berizin) or a registration (S-…, terdaftar).
CREATE TABLE published_market.entity (
    id             text PRIMARY KEY,
    company_id     text NOT NULL REFERENCES published_market.company (id) ON DELETE CASCADE,
    register       text NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('license', 'registration', 'unknown')),
    license_number text NOT NULL,
    license_date   date,
    legal_name     text NOT NULL,
    names          text[] NOT NULL,
    business_type  text NOT NULL CHECK (business_type IN ('sharia', 'conventional', 'unknown')),
    website        text,
    channels       text[] NOT NULL,
    first_listed   date NOT NULL,
    last_listed    date NOT NULL,
    on_newest_list boolean NOT NULL,
    left_after     date,
    review_notes   text[] NOT NULL DEFAULT '{}'      -- what is unclear; a note never holds an entity back
);
CREATE INDEX published_market_entity_company_idx ON published_market.entity (company_id);

CREATE TABLE published_market.listing (
    entity_id  text NOT NULL REFERENCES published_market.entity (id) ON DELETE CASCADE,
    edition    date NOT NULL,
    legal_name text NOT NULL,
    page       integer NOT NULL,
    row_number integer NOT NULL,
    cells      jsonb NOT NULL,                       -- the row under its printed headers
    PRIMARY KEY (entity_id, edition)
);
