-- Phase 4, Step 6 (docs/market-data-layer-plan.md): curated links from registers and industries to their reports,
-- and the industries published, the retrieval tools' bridge between the market layer and the law. A link names a
-- report (ojk:roadmap:2023:rp3si) or a family (ojk:lpksi: every edition published). Curated, never inferred.

ALTER TABLE market.register ADD COLUMN reports text[] NOT NULL DEFAULT '{}';
ALTER TABLE market.industry ADD COLUMN reports text[] NOT NULL DEFAULT '{}';

UPDATE market.register SET reports = '{ojk:roadmap:2023:lpbbti}' WHERE id = 'ojk:lpbbti';
-- LPKSI and KEKSI cover every sharia industry; RP3SI sharia banks (BUS, UUS, BPRS); the LPBBTI roadmap fintech lending
UPDATE market.industry SET reports = '{ojk:lpksi,ojk:roadmap:2023:lpbbti,bi:keksi}'
WHERE source = 'ojk:portal' AND name = 'Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Syariah';
UPDATE market.industry SET reports = '{ojk:roadmap:2023:lpbbti}'
WHERE source = 'ojk:portal' AND name = 'Layanan Pendanaan Bersama Berbasis Teknologi Informasi (LPBBTI) Konvensional';
UPDATE market.industry SET reports = '{ojk:lpksi,ojk:roadmap:2023:rp3si,bi:keksi}'
WHERE source = 'ojk:portal' AND name IN ('Bank Umum Syariah', 'Bank Perekonomian Rakyat (BPR) Syariah');

ALTER TABLE published_market.register ADD COLUMN reports text[] NOT NULL DEFAULT '{}';
ALTER TABLE published_market.dataset ADD COLUMN reports text[] NOT NULL DEFAULT '{}';

CREATE TABLE published_market.industry (
    source       text NOT NULL,
    name         text NOT NULL,                      -- as the source names it
    register     text,
    governed_by  text[] NOT NULL,                    -- its register's regulations, or its own
    reports      text[] NOT NULL,                    -- the published reports its links name, each family newest first
    datasets     text[] NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, name)
);
COMMENT ON TABLE published_market.industry IS
    'Each curated industry with its register, regulations, reports and datasets: from a market question to the law.';
