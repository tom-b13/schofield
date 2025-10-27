-- Epic G — Build questionnaire (PostgreSQL migration)
-- Ensure ordering columns and supporting indexes/constraints exist.

-- Screens: add screen_order if missing and enforce uniqueness per questionnaire
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'screen' AND column_name = 'screen_order'
    ) THEN
        ALTER TABLE screen ADD COLUMN screen_order INTEGER NOT NULL DEFAULT 1;
    END IF;
END $$;

-- Unique contiguous ordering is enforced by application logic; add indexes to support reindex operations
DO $$
BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS idx_screen_qid_order ON screen(questionnaire_id, screen_order);
    CREATE INDEX IF NOT EXISTS idx_screen_by_qid ON screen(questionnaire_id);
END $$;

-- Questions: ensure question_order column exists and is indexed for per-screen ordering
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'questionnaire_question' AND column_name = 'question_order'
    ) THEN
        ALTER TABLE questionnaire_question ADD COLUMN question_order INTEGER;
        -- Application will backfill and enforce contiguity; leave NULLs for legacy rows
    END IF;
    CREATE INDEX IF NOT EXISTS idx_question_by_screen_order ON questionnaire_question(screen_key, question_order);
END $$;

-- end-of-file
