-- What the loader needs beyond 0001-0002: the outcome of a failed bundle, documents a snapshot no longer
-- lists, and an alias's readable text beside its lookup key.

ALTER TABLE ingest.bundle
    ADD COLUMN missing integer NOT NULL DEFAULT 0,          -- source records newly absent from this snapshot
    ADD COLUMN error   text;                                -- why the load failed (state = 'failed')

ALTER TABLE registry.alias
    ADD COLUMN text text NOT NULL DEFAULT '';               -- as the source wrote it, e.g. "POJK 5/POJK.05/2014"
ALTER TABLE registry.alias ALTER COLUMN text DROP DEFAULT;
