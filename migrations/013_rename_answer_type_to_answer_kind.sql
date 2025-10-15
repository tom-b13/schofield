-- Align QuestionnaireQuestion column with ERD: answer_type -> answer_kind
DO $$ BEGIN
    -- Only perform rename if the old column exists and the new one does not
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'questionnaire_question' AND column_name = 'answer_type'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'questionnaire_question' AND column_name = 'answer_kind'
    ) THEN
        ALTER TABLE questionnaire_question RENAME COLUMN answer_type TO answer_kind;
    END IF;
END $$;

