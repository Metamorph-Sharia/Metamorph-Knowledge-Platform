-- A reranker reads only the start of a unit, about 1,500 characters, so a point late in a long unit cannot be found:
-- 36% of OJK circulars' (SEOJK) units and 27% of BI circulars' (SEBI) units run past 2,000 characters, and one
-- section with its numbered points inside runs to 7,000. A unit longer than 2,000 characters therefore hands its
-- direct items (huruf, angka) to retrieval as units of their own, one level down; the long unit stays one unit, and
-- an item's own items stay inside its wording, however long it is.
CREATE OR REPLACE VIEW published.provision_unit AS
WITH unit AS (
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
      )
),
item AS (
    -- only a unit's direct items become units: an item's own items stay inside it, so one level down, never more
    SELECT i.document_id, i.address, i.kind, i.label, i.heading, i.heading_path, i.wording, i.text_sha256,
           i.page_start, i.page_end, i.valid_from, i.valid_to,
           d.issuer, d.family, d.number, d.year, d.citation, d.title, d.status, d.effective_on,
           e.address AS elucidation_address,
           EXISTS (
               SELECT 1 FROM published.review r
               WHERE r.document_id = i.document_id AND r.address IN (i.address, i.parent_address)
           ) AS under_review
    FROM unit u
    JOIN published.provision i ON i.document_id = u.document_id AND i.parent_address = u.address
    JOIN published.document d ON d.id = i.document_id
    LEFT JOIN published.provision e ON e.document_id = i.document_id AND e.address = 'penjelasan/' || i.address
    WHERE char_length(u.wording) > 2000
      AND i.kind IN ('huruf', 'angka')
      AND i.wording <> ''
)
SELECT document_id, address, kind, label, heading, heading_path, wording, text_sha256,
       page_start, page_end, valid_from, valid_to,
       issuer, family, number, year, citation, title, status, effective_on,
       elucidation_address, under_review
FROM unit
UNION ALL
SELECT document_id, address, kind, label, heading, heading_path, wording, text_sha256,
       page_start, page_end, valid_from, valid_to,
       issuer, family, number, year, citation, title, status, effective_on,
       elucidation_address, under_review
FROM item;
