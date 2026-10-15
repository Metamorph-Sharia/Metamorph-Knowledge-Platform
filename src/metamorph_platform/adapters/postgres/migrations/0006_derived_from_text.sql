-- What the platform derives from the texts themselves (Phase 5): structure, citations, stated dates, validity.

-- Each text remembers which parser version read it, what looked wrong, and the dates it states about itself.
ALTER TABLE registry.text_version
    ADD COLUMN parsed_with           text,           -- parser version; NULL until parsed
    ADD COLUMN structure_problems    jsonb,          -- [] when the structure passed every quality check
    ADD COLUMN stated_enacted_on     date,           -- "Ditetapkan di … pada tanggal …"
    ADD COLUMN stated_promulgated_on date,           -- "Diundangkan di … pada tanggal …"
    ADD COLUMN stated_effective_on   date;           -- "… mulai berlaku pada tanggal …"

-- A citation is a source's claim, or one the parser found in a text. Parsed ones belong to their text
-- version, not to a source record, so reloading a source never deletes them.
ALTER TABLE registry.citation
    ADD COLUMN origin text NOT NULL DEFAULT 'source' CHECK (origin IN ('source', 'parsed')),
    ADD COLUMN text_version_id bigint REFERENCES registry.text_version (id),
    ALTER COLUMN connector DROP NOT NULL,
    ALTER COLUMN source_id DROP NOT NULL,
    ADD CONSTRAINT citation_owner_check CHECK (
        (origin = 'source' AND connector IS NOT NULL AND source_id IS NOT NULL)
        OR (origin = 'parsed' AND text_version_id IS NOT NULL));
CREATE INDEX citation_text_version_idx ON registry.citation (text_version_id) WHERE text_version_id IS NOT NULL;

-- Links are rebuilt from citations; one no citation supports any more is dropped, and what hung off it goes too.
ALTER TABLE registry.citation DROP CONSTRAINT citation_link_id_fkey,
    ADD CONSTRAINT citation_link_id_fkey FOREIGN KEY (link_id) REFERENCES registry.link (id) ON DELETE SET NULL;
ALTER TABLE registry.status_event DROP CONSTRAINT status_event_link_id_fkey,
    ADD CONSTRAINT status_event_link_id_fkey FOREIGN KEY (link_id) REFERENCES registry.link (id) ON DELETE CASCADE;

-- A document can have more than one main text (BI publishes some bodies and elucidations as separate PDFs),
-- and each is parsed on its own, so a published provision is addressed within its text.
ALTER TABLE published.provision DROP CONSTRAINT provision_pkey,
    ADD PRIMARY KEY (document_id, text_sha256, address);
