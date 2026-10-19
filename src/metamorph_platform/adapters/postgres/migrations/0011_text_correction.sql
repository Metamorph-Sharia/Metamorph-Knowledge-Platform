-- Text correction: a curator's corrected wording of a current main text, an overlay like a field correction.
-- The source text is never edited; parsing and publishing read the correction while it is active and the
-- text it corrects is still current.

-- The content the parser last read: the text's own, or its correction's.
ALTER TABLE registry.text_version ADD COLUMN parsed_sha256 text;
UPDATE registry.text_version SET parsed_sha256 = sha256 WHERE parsed_with IS NOT NULL;

-- The corrected wording sits in the blob store beside the source's (content-addressed); one active correction
-- per source text, and a new one replaces it. An inactive row is history: what was corrected, by whom, why.
CREATE TABLE curation.text_correction (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     text NOT NULL REFERENCES registry.document (id) ON UPDATE CASCADE,
    corrects_sha256 text NOT NULL,                     -- the source text it corrects
    sha256          text NOT NULL,                     -- the corrected wording
    storage_key     text NOT NULL,
    reason          text NOT NULL,                     -- where the corrected wording comes from, e.g. a PDF page
    author          text NOT NULL REFERENCES curation.curator (username),
    created_at      timestamptz NOT NULL DEFAULT now(),
    active          boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX text_correction_active_idx ON curation.text_correction (document_id, corrects_sha256) WHERE active;
