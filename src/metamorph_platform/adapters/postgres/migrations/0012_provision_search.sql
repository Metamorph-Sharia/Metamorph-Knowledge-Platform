-- Searching the published articles' wording: what the curation console's search finds inside the texts.
-- The 'simple' configuration (lower-cased words, no stemming): PostgreSQL ships no Indonesian stemmer, and
-- curators search for the words a regulation uses. Only published provisions are searched (a decision of
-- docs/pasal-id-gap-analysis.md §7): a held document that was never published is found by its metadata.
ALTER TABLE published.provision
    ADD COLUMN search tsvector GENERATED ALWAYS AS (to_tsvector('simple', body)) STORED;
CREATE INDEX provision_search_idx ON published.provision USING gin (search);
