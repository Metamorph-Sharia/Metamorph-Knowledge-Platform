-- How a text was read from its file (contract 2.1, TextRef.extraction): the engine and its exact version, its
-- tier and mode, the pages it OCR'd and the pages that fell back to the file's own text layer. NULL for a text
-- a connector read with its own PDF reading, as every text before 2.1, and for texts taken from a source.
ALTER TABLE registry.text_version ADD COLUMN extraction jsonb;
ALTER TABLE published.text ADD COLUMN extraction jsonb;
