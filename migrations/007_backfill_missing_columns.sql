-- Remedial migration to backfill critical columns on pre-existing tables
-- Clarke guidance: ensure required columns exist even if base tables were created earlier
-- without these fields. This migration is idempotent via IF NOT EXISTS clauses.

-- questionnaire_question.screen_key
ALTER TABLE questionnaire_question
    ADD COLUMN IF NOT EXISTS screen_key TEXT;

-- answer_option.sort_index
ALTER TABLE answer_option
    ADD COLUMN IF NOT EXISTS sort_index INT;

-- response.answered_at (align with base schema default)
ALTER TABLE response
    ADD COLUMN IF NOT EXISTS answered_at TIMESTAMPTZ DEFAULT now();

