-- What the Knowledge and Retrieval layer embeds and walks (docs/mineru-extraction-plan.md, step 6).
-- A provision gains the path it is read under, its depth and its wording: the body without its own heading lines
-- or page furniture. Rows published before this migration keep the defaults until they are published again.
ALTER TABLE published.provision
    ADD COLUMN heading_path text[] NOT NULL DEFAULT '{}',  -- "BAB II KEGIATAN USAHA", "Pasal 5", "(1)"
    ADD COLUMN depth integer NOT NULL DEFAULT 0,           -- how many provisions hold it
    ADD COLUMN wording text NOT NULL DEFAULT '';           -- the body to read or embed; empty for a grouping heading
CREATE INDEX published_provision_parent_idx ON published.provision (document_id, parent_address);

-- The retrieval units: the smallest provisions with wording of their own, with what to read them under. A paragraph
-- with its items is one unit (its items stay addressable in published.provision, to split a long one by); an article
-- whose paragraphs carry its wording is not one, its paragraphs are.
CREATE VIEW published.provision_unit AS
SELECT p.document_id, p.address, p.kind, p.label, p.heading, p.heading_path, p.wording, p.text_sha256,
       p.page_start, p.page_end, p.valid_from, p.valid_to,
       d.issuer, d.family, d.number, d.year, d.citation, d.title, d.status, d.effective_on,
       e.address AS elucidation_address
FROM published.provision p
JOIN published.document d ON d.id = p.document_id
LEFT JOIN published.provision e ON e.document_id = p.document_id AND e.address = 'penjelasan/' || p.address
WHERE p.wording <> ''
  AND p.kind NOT IN ('huruf', 'angka')
  AND NOT EXISTS (
      SELECT 1 FROM published.provision c
      WHERE c.document_id = p.document_id AND c.parent_address = p.address
        AND c.kind NOT IN ('huruf', 'angka') AND c.wording <> ''
  );

-- Every edge of the graph in one place: the links (citations, amendments, legal basis, a provision's references to
-- the document's other provisions) and the structure: what contains what, and what elucidates what.
CREATE VIEW published.edge AS
SELECT type, from_document, from_address, to_document, to_address, effective_on, confidence
FROM published.link
UNION ALL
SELECT 'contains', document_id, parent_address, document_id, address, NULL::date, 'high'
FROM published.provision
WHERE parent_address IS NOT NULL
UNION ALL
SELECT 'elucidates', e.document_id, e.address, e.document_id, p.address, NULL::date, 'high'
FROM published.provision e
JOIN published.provision p ON p.document_id = e.document_id AND e.address = 'penjelasan/' || p.address;
