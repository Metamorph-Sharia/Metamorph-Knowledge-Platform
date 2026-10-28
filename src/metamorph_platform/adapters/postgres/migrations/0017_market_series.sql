-- Phase 2 of the market data layer (docs/market-data-layer-plan.md): statistics as series, from OJK's data portal.
-- market.series holds what connectors sent; published_market's dataset, series and observation are its read contract.

-- A statistics source is curated: how old its newest month may be.
CREATE TABLE market.statistics_source (
    id         text PRIMARY KEY,                     -- {issuer}:{source}, as series' datasets start
    issuer     text NOT NULL,
    name       text NOT NULL,
    fresh_days integer NOT NULL                      -- health warns when the newest month ended longer ago
);
INSERT INTO market.statistics_source (id, issuer, name, fresh_days) VALUES (
    'ojk:portal', 'ojk', 'Portal Data dan Metadata Sektor Jasa Keuangan Terintegrasi (data.ojk.go.id)',
    120  -- OJK publishes a month about two months after it ends
);

-- How a source's industries link to the regulation layer: through a register, whose regulations they share,
-- or through regulations of their own. Curated, never inferred; an industry without a row is published unlinked.
CREATE TABLE market.industry (
    source      text NOT NULL REFERENCES market.statistics_source (id),
    name        text NOT NULL,                       -- as the source names it
    register    text REFERENCES market.register (id),
    governed_by text[] NOT NULL DEFAULT '{}',        -- regulation document IDs, when it has no register
    PRIMARY KEY (source, name)
);
INSERT INTO market.industry (source, name, register, governed_by) VALUES
    ('ojk:portal', 'Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Konvensional', 'ojk:lpbbti', '{}'),
    ('ojk:portal', 'Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah', 'ojk:lpbbti', '{}'),
    -- the sharia banking law; POJK 16/2022 (Bank Umum Syariah); POJK 12/2023 (Unit Usaha Syariah)
    ('ojk:portal', 'Bank Umum Syariah', NULL, '{id:uu:2008:21,ojk:pojk:2022:16,ojk:pojk:2023:12}'),
    -- the sharia banking law; POJK 7/2024 (BPR dan BPR Syariah)
    ('ojk:portal', 'Bank Perekonomian Rakyat (BPR) Syariah', NULL, '{id:uu:2008:21,ojk:pojk:2024:7}');

-- One series as received: the record whole, as the source of every published value.
CREATE TABLE market.series (
    id            text PRIMARY KEY,                  -- the record's series.id
    source        text NOT NULL REFERENCES market.statistics_source (id),
    connector     text NOT NULL,
    source_id     text NOT NULL,
    package_hash  text NOT NULL,
    record        jsonb NOT NULL,
    bundle_id     bigint NOT NULL REFERENCES ingest.bundle (id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    missing_since timestamptz,
    UNIQUE (connector, source_id)
);

-- One of the source's tables, e.g. a portal cube: its industry's links, and the months it holds.
CREATE TABLE published_market.dataset (
    id           text PRIMARY KEY,
    source       text NOT NULL,
    industry     text NOT NULL,
    "group"      text NOT NULL,
    metric       text NOT NULL,
    register     text,                               -- the register of the industry's licensed entities
    governed_by  text[] NOT NULL,
    series       integer NOT NULL,
    first_period date NOT NULL,                      -- months, as their first day
    last_period  date NOT NULL,
    updated      date,                               -- when the source last updated the data
    url          text,
    published_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE published_market.series (
    id           text PRIMARY KEY,
    dataset      text NOT NULL REFERENCES published_market.dataset (id) ON DELETE CASCADE,
    measure      text NOT NULL,
    label        text NOT NULL,                      -- the measure and its members' labels
    dimensions   jsonb NOT NULL,                     -- [{name, key, label}], which slice of the table
    first_period date NOT NULL,
    last_period  date NOT NULL,
    observations integer NOT NULL
);
CREATE INDEX published_market_series_dataset_idx ON published_market.series (dataset);

CREATE TABLE published_market.observation (
    series_id   text NOT NULL REFERENCES published_market.series (id) ON DELETE CASCADE,
    period      date NOT NULL,                       -- the month's first day
    value       double precision NOT NULL,           -- as the source gives it, never rescaled
    storage_key text,                                -- the answer it was read from, in the object store
    PRIMARY KEY (series_id, period)
);
