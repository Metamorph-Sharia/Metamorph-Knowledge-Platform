-- Rolling the publish gate out, once. From here on `published` only holds versions that passed the gate
-- (domain/gate.py), so what was published before it and fails it now is withdrawn: those versions were
-- never good. Apply it after a build, when every main text is parsed (on 2026-10-19 all were, by parser 4).
-- The same checks as the gate, over what the registry stores; no approval exists yet.

WITH main_text AS (
    SELECT t.document_id, t.parsed_with, coalesce(t.structure_problems, '[]'::jsonb) AS problems
    FROM registry.text_version t
    WHERE t.is_current AND t.language = 'id'
      AND (t.of_file IS NULL OR EXISTS (
            SELECT 1 FROM registry.document_file f
            WHERE f.document_id = t.document_id AND f.sha256 = t.of_file AND f.role = 'main'))
), failing AS (
    SELECT d.id FROM registry.document d
    WHERE d.id LIKE 'unresolved:%'
       OR NOT EXISTS (SELECT 1 FROM main_text m WHERE m.document_id = d.id)
       OR EXISTS (SELECT 1 FROM main_text m
                  WHERE m.document_id = d.id AND (m.parsed_with IS NULL OR jsonb_array_length(m.problems) > 0))
), withdrawn AS (
    DELETE FROM published.document p USING failing f WHERE p.id = f.id RETURNING p.id
)
INSERT INTO published.change_log (document_id, change) SELECT id, 'removed' FROM withdrawn;

-- The review items the gate replaces: structure and identity are hold reasons now. Closed as the platform,
-- audited like a curator's decision.
INSERT INTO curation.curator (username, display_name) VALUES ('metamorph-platform', 'Metamorph platform (automatic)')
ON CONFLICT (username) DO NOTHING;

WITH closed AS (
    UPDATE curation.review_item
    SET state = 'resolved', decided_by = 'metamorph-platform', decided_at = now(), note = 'replaced by the publish gate'
    WHERE state = 'open' AND kind IN ('structure_suspect', 'unresolved_id')
    RETURNING id, kind, subject
)
INSERT INTO curation.audit_log (author, action, target, before, after, reason)
SELECT 'metamorph-platform', 'decide_review', jsonb_build_object('review_item_id', id),
       jsonb_build_object('state', 'open', 'kind', kind, 'subject', subject), '{"state": "resolved"}'::jsonb,
       'replaced by the publish gate'
FROM closed;
