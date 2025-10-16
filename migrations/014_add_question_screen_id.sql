-- EPIC G/A: Introduce screen_id on questionnaire_question for per-screen ordering and FK
ALTER TABLE questionnaire_question
    ADD COLUMN IF NOT EXISTS screen_id uuid NOT NULL;

