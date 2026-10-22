-- Structure warnings, published for review instead of holding the document (domain/gate.py): a gap in a text's
-- numbering costs a unit's boundary, not its words. A note is on the provision it names ("pasal-4: ayat (2)
-- missing"), or on the document when it names none ("Pasal 9 missing").
CREATE TABLE published.review (
    document_id text NOT NULL REFERENCES published.document (id) ON DELETE CASCADE,
    ordinal integer NOT NULL,  -- the parser's order: the text's reading order
    address text,  -- the provision the note is about; NULL: the document
    note text NOT NULL
);
CREATE INDEX published_review_document_idx ON published.review (document_id);

-- A retrieval unit is under review when a note is on it or on its parent: "pasal-87: ayat (3) missing" is about
-- pasal-87's own paragraphs, not the articles an amending pasal-87 quotes.
CREATE OR REPLACE VIEW published.provision_unit AS
SELECT p.document_id, p.address, p.kind, p.label, p.heading, p.heading_path, p.wording, p.text_sha256,
       p.page_start, p.page_end, p.valid_from, p.valid_to,
       d.issuer, d.family, d.number, d.year, d.citation, d.title, d.status, d.effective_on,
       e.address AS elucidation_address,
       EXISTS (
           SELECT 1 FROM published.review r
           WHERE r.document_id = p.document_id AND r.address IN (p.address, p.parent_address)
       ) AS under_review
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
