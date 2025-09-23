-- 2025-09-23T18:21:32.087870Z
-- Epic A.1 migration: parent value condition fields and index

-- Add new columns to questionnaire_question
ALTER TABLE questionnaire_question
    ADD COLUMN IF NOT EXISTS parent_question_id uuid,
    ADD COLUMN IF NOT EXISTS visible_if_value text;

-- Create index to support lookups by parent
CREATE INDEX IF NOT EXISTS ix_question_parent_question_id ON questionnaire_question(parent_question_id);

-- Foreign key: parent_question_id → questionnaire_question(question_id)
ALTER TABLE questionnaire_question
    ADD CONSTRAINT IF NOT EXISTS fk_question_parent_question
        FOREIGN KEY (parent_question_id) REFERENCES questionnaire_question(question_id) ON DELETE RESTRICT;
