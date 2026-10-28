-- Phase 3 of the market data layer (docs/market-data-layer-plan.md): macro statistics from BI's SEKI tables and
-- BPS's dynamic tables. Series now come by month, quarter, half-year or year, with a unit and provisional marks,
-- and a macro dataset belongs to no industry. Each source says how it asks to be cited.

ALTER TABLE market.statistics_source ADD COLUMN citation text;  -- how answers cite the source
UPDATE market.statistics_source
SET citation = 'Otoritas Jasa Keuangan, Portal Data dan Metadata Sektor Jasa Keuangan Terintegrasi (data.ojk.go.id)'
WHERE id = 'ojk:portal';
INSERT INTO market.statistics_source (id, issuer, name, fresh_days, citation) VALUES
    ('bi:seki', 'bi', 'Statistik Ekonomi dan Keuangan Indonesia (SEKI)',
     90,   -- BI publishes a month about five weeks after it ends
     'Bank Indonesia, Statistik Ekonomi dan Keuangan Indonesia (SEKI)'),
    ('bps:table', 'bps', 'Tabel dinamis Badan Pusat Statistik (bps.go.id)',
     120,  -- BPS's monthly tables (prices) appear within weeks; most others are yearly
     -- BPS's terms ask for the content's title, the date it was accessed and a direct link: the dataset's
     -- metric, its published_at and its url
     'Badan Pusat Statistik (BPS), bps.go.id');

-- The 1.0 contract now always writes a series' frequency and unit and an observation's mark. Phase 2's records,
-- written before, are monthly, state no unit and carry no marks.
UPDATE market.series
SET record = jsonb_set(
    jsonb_set(jsonb_set(record, '{series,frequency}', '"monthly"'), '{series,unit}', 'null'),
    '{observations}',
    (SELECT jsonb_agg(observation || '{"provisional": false}' ORDER BY position)
     FROM jsonb_array_elements(record -> 'observations') WITH ORDINALITY AS listed (observation, position)))
WHERE NOT (record -> 'series' ? 'frequency');

ALTER TABLE published_market.dataset ALTER COLUMN industry DROP NOT NULL;  -- NULL: a macro dataset
ALTER TABLE published_market.dataset ADD COLUMN citation text;

ALTER TABLE published_market.series
    ADD COLUMN frequency text NOT NULL DEFAULT 'monthly'
        CHECK (frequency IN ('monthly', 'quarterly', 'semiannual', 'annual')),
    ADD COLUMN unit text;                                -- as the source states it
ALTER TABLE published_market.series ALTER COLUMN frequency DROP DEFAULT;
COMMENT ON COLUMN published_market.series.first_period IS 'the first period''s first day, by frequency';

ALTER TABLE published_market.observation ADD COLUMN provisional boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN published_market.observation.period IS 'the period''s first day: 2026-Q2 is 2026-04-01';
