-- Curation (Phase 7): curator-assigned IDs, and renaming a document in one statement.

-- A curator renames a document its connector couldn't identify; every row about it follows the new ID.
ALTER TABLE registry.alias DROP CONSTRAINT alias_document_id_fkey,
    ADD CONSTRAINT alias_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.citation DROP CONSTRAINT citation_document_id_fkey,
    ADD CONSTRAINT citation_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.document_file DROP CONSTRAINT document_file_document_id_fkey,
    ADD CONSTRAINT document_file_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.document_source DROP CONSTRAINT document_source_document_id_fkey,
    ADD CONSTRAINT document_source_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.link DROP CONSTRAINT link_from_document_fkey,
    ADD CONSTRAINT link_from_document_fkey FOREIGN KEY (from_document) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.link DROP CONSTRAINT link_to_document_fkey,
    ADD CONSTRAINT link_to_document_fkey FOREIGN KEY (to_document) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE curation.override DROP CONSTRAINT override_document_id_fkey,
    ADD CONSTRAINT override_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.provision DROP CONSTRAINT provision_document_id_fkey,
    ADD CONSTRAINT provision_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.status_event DROP CONSTRAINT status_event_document_id_fkey,
    ADD CONSTRAINT status_event_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE curation.suppression DROP CONSTRAINT suppression_document_id_fkey,
    ADD CONSTRAINT suppression_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;
ALTER TABLE registry.text_version DROP CONSTRAINT text_version_document_id_fkey,
    ADD CONSTRAINT text_version_document_id_fkey FOREIGN KEY (document_id) REFERENCES registry.document (id) ON UPDATE CASCADE;

-- The ID a curator gave a source record. The loader applies it on every later load of that record.
CREATE TABLE curation.id_assignment (
    connector   text NOT NULL,
    source_id   text NOT NULL,
    document_id text NOT NULL,
    author      text NOT NULL REFERENCES curation.curator (username),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connector, source_id),
    FOREIGN KEY (connector, source_id) REFERENCES registry.document_source (connector, source_id)
);

-- A source keeps changing a corrected field: one open conflict per override, updated with the latest value.
CREATE UNIQUE INDEX conflict_open_idx ON curation.conflict (override_id) WHERE state = 'open';

-- Why a curator did what they did, for the next reviewer.
ALTER TABLE curation.audit_log ADD COLUMN reason text;
