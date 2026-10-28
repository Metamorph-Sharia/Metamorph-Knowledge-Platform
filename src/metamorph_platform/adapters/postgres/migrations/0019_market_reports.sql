-- Phase 4 of the market data layer (docs/market-data-layer-plan.md): regulators' reports, roadmaps and masterplans
-- (LPKSI, KEKSI, RP3SI, …), kept out of the regulation layer. A report has no legal force: it says what a
-- regulator reports or plans, never a rule. Its passages are cut by the platform from the text a connector read.

-- One report as received: the record whole, with its PDF and its text in market.file.
CREATE TABLE market.report (
    id            text PRIMARY KEY,                  -- the record's report.id, e.g. ojk:lpksi:2025
    issuer        text NOT NULL,
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

CREATE TABLE published_market.report (
    id           text PRIMARY KEY,
    issuer       text NOT NULL,
    family       text NOT NULL,                      -- lpksi, keksi, roadmap …
    edition      text NOT NULL,                      -- as titled: 2025, 2023-2027
    title        text NOT NULL,
    published_on date,
    language     text NOT NULL,
    url          text,                               -- the page that lists it
    citation     text NOT NULL,                      -- the issuer and the title
    pages        integer NOT NULL,
    passages     integer NOT NULL,
    method       text NOT NULL,                      -- text_layer, or ocr when any page was read by OCR
    storage_key  text,                               -- the PDF in the object store
    published_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE published_market.report IS 'A regulator''s report, roadmap or masterplan. No legal force: never a rule.';

CREATE TABLE published_market.report_passage (
    report     text NOT NULL REFERENCES published_market.report (id) ON DELETE CASCADE,
    address    text NOT NULL,                        -- p-1, p-2 … in reading order
    ordinal    integer NOT NULL,
    page_start integer NOT NULL,
    page_end   integer NOT NULL,
    text       text NOT NULL,                        -- about 250 to 400 words: what to read, cite and embed
    words      integer NOT NULL,
    PRIMARY KEY (report, address)
);
