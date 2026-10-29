-- Phase 5 of the market data layer (docs/market-data-layer-plan.md): OJK's press releases, and what the passages of
-- every report and release name. A release has no legal force: it says what a regulator announced, and one
-- announcing a regulation is not the regulation. A mention says "names", never "revokes" or "issues".

-- One release as received: the record whole, its words in it, its body in market.file.
CREATE TABLE market.release (
    id            text PRIMARY KEY,                  -- the record's release.id, e.g. ojk:siaran-pers:2026:ojk-cabut-izin-…
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

CREATE TABLE published_market.release (
    id           text PRIMARY KEY,
    issuer       text NOT NULL,
    number       text,                               -- as printed, e.g. SP 188/DKPU/OJK/X/2026; numbers repeat yearly
    title        text NOT NULL,                      -- as listed
    published_on date NOT NULL,                      -- as the listing dates it
    language     text NOT NULL,
    url          text,                               -- its page
    citation     text NOT NULL,                      -- e.g. Siaran Pers OJK SP 188/DKPU/OJK/X/2026, 8 Oktober 2026
    passages     integer NOT NULL,
    storage_key  text,                               -- its body as published, in the object store
    published_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE published_market.release IS 'A regulator''s press release. No legal force: never a rule.';
CREATE INDEX release_published_on ON published_market.release (published_on DESC);

CREATE TABLE published_market.release_passage (
    release text NOT NULL REFERENCES published_market.release (id) ON DELETE CASCADE,
    address text NOT NULL,                           -- p-1, p-2 … in reading order
    ordinal integer NOT NULL,
    text    text NOT NULL,                           -- up to 400 words: what to read, cite and embed
    words   integer NOT NULL,
    PRIMARY KEY (release, address)
);

-- What each passage of a report or a release names: a regulation (by the regulation layer's reference grammar)
-- or a company (by its full legal name). Each target once a passage, as first written.
CREATE TABLE published_market.mention (
    kind        text NOT NULL CHECK (kind IN ('report', 'release')),
    document    text NOT NULL,                       -- the report's or the release's ID
    address     text NOT NULL,                       -- the passage's
    target_kind text NOT NULL CHECK (target_kind IN ('regulation', 'company')),
    target      text NOT NULL,                       -- a regulation's ID (it may not be published) or a company's
    words       text NOT NULL,                       -- as written
    PRIMARY KEY (document, address, target_kind, target)
);
CREATE INDEX mention_target ON published_market.mention (target_kind, target);
COMMENT ON TABLE published_market.mention IS 'A passage names a regulation or a company: never what it did to it.';
