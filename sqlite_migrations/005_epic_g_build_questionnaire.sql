-- Epic G — Build questionnaire (SQLite migration)
-- Adds backend-authoritative ordering columns and supporting indexes.

PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Screens: add contiguous order column (1-based, NOT NULL) for per-questionnaire ordering
-- If the column already exists, this statement will fail; apply once.
ALTER TABLE screens ADD COLUMN screen_order INTEGER NOT NULL DEFAULT 1;

-- Unique ordering per questionnaire: no gaps are enforced by application logic
-- Indexes help contiguous reindex operations and fetches.
CREATE UNIQUE INDEX IF NOT EXISTS idx_screens_qid_order ON screens(questionnaire_id, screen_order);
CREATE INDEX IF NOT EXISTS idx_screens_by_qid ON screens(questionnaire_id);

-- Questions: ensure ordering column is present and indexed for per-screen ordering
-- (Column typically exists from earlier migrations; application enforces contiguity.)
CREATE INDEX IF NOT EXISTS idx_question_by_screen_order ON questionnaire_question(screen_key, question_order);

COMMIT;

-- end-of-file

