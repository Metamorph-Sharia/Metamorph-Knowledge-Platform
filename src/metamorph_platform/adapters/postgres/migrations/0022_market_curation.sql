-- Curating the market layer (docs/market-curation-plan.md). From here on, curators keep the curated links through the
-- curation API (audited in curation.audit_log); migrations change the schema and no longer write links.
-- Added: where a curator downloads an edition by hand (SEKI, Phase 3 option A), and sectors, one curated list of
-- industries across the sources' own names, for the retrieval layer's industry_context.

ALTER TABLE market.statistics_source ADD COLUMN download_page text, ADD COLUMN download_hint text;
-- The one value written here: the source's own setting, which curators correct from now on
UPDATE market.statistics_source
SET download_page = 'https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/Default.aspx',
    download_hint = 'Each month''s edition is one zip under Documents/, e.g. SEKI_SEPTEMBER_2026.zip (published '
                    '15 October 2026). Put it in BI-Stats-Connector/data/inbox/: the Monday run imports it.'
WHERE id = 'bi:seki';

CREATE TABLE market.sector (
    id      text PRIMARY KEY,                       -- e.g. sharia-banking
    name    text NOT NULL,                          -- in Indonesian
    name_en text NOT NULL DEFAULT ''
);
CREATE TABLE market.sector_industry (
    sector  text NOT NULL REFERENCES market.sector (id) ON DELETE CASCADE,
    source  text NOT NULL REFERENCES market.statistics_source (id),
    name    text NOT NULL,                          -- the industry as the source names it
    ordinal integer NOT NULL,                       -- the curator's order
    PRIMARY KEY (sector, source, name)
);
COMMENT ON TABLE market.sector IS
    'One curated industry across the sources'' own names (market.sector_industry). Curated, never inferred.';

CREATE TABLE published_market.sector (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    name_en      text NOT NULL,
    industries   jsonb NOT NULL,                     -- [{source, name}]
    registers    text[] NOT NULL,
    governed_by  text[] NOT NULL,                    -- its industries' regulations, each once
    reports      text[] NOT NULL,
    datasets     text[] NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE published_market.sector IS
    'Each curated sector with what its industries link: registers, regulations, reports and datasets.';
