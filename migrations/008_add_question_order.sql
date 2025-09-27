-- Remedial migration to add questionnaire_question.question_order
-- Clarke guidance: ensure the column exists before Background seeding.
-- Idempotent via IF NOT EXISTS; compatible with PostgreSQL and SQLite >= 3.35.

ALTER TABLE questionnaire_question
    ADD COLUMN IF NOT EXISTS question_order INT;

