-- EPIC G/A: Introduce screen_id on questionnaire_question for per-screen ordering and FK
-- Make the migration safe for existing rows: add nullable, backfill, then enforce NOT NULL
ALTER TABLE questionnaire_question
    ADD COLUMN IF NOT EXISTS screen_id uuid;

-- Backfill from existing screen_key mapping only if 'screen' table exists
DO $do$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'screen'
  ) THEN
    UPDATE questionnaire_question AS qq
    SET screen_id = s.screen_id
    FROM screen AS s
    WHERE qq.screen_id IS NULL AND qq.screen_key = s.screen_key;
  END IF;
END
$do$;

-- Enforce NOT NULL only if no NULLs remain after backfill
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM questionnaire_question WHERE screen_id IS NULL) THEN
    ALTER TABLE questionnaire_question
        ALTER COLUMN screen_id SET NOT NULL;
  END IF;
END
$do$;
