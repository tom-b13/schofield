-- Drop indexes (IF EXISTS to be safe)
DROP INDEX IF EXISTS ix_generated_document_created;
DROP INDEX IF EXISTS ix_generated_document_set;

DROP INDEX IF EXISTS ix_group_value_source_q;
DROP INDEX IF EXISTS ix_group_value_group;
DROP INDEX IF EXISTS ix_group_value_set;

DROP INDEX IF EXISTS ix_response_option;
DROP INDEX IF EXISTS ix_response_question;
DROP INDEX IF EXISTS ix_response_set;

DROP INDEX IF EXISTS ix_response_set_created_at;
DROP INDEX IF EXISTS ix_response_set_company;

DROP INDEX IF EXISTS ix_q2fg_group;
DROP INDEX IF EXISTS ix_q2fg_question;

DROP INDEX IF EXISTS ix_field_group_key;

DROP INDEX IF EXISTS ix_q2s_question;
DROP INDEX IF EXISTS ix_q2s_screen_sort;

DROP INDEX IF EXISTS ix_screen_active;
DROP INDEX IF EXISTS ix_screen_sort;

DROP INDEX IF EXISTS ix_answer_option_question;
DROP INDEX IF EXISTS uq_answer_option_question_value;

DROP INDEX IF EXISTS ix_question_answer_type;
DROP INDEX IF EXISTS ix_question_section;
DROP INDEX IF EXISTS uq_question_placeholder_code;

-- Drop constraints that aren't cascaded by table drops
ALTER TABLE group_value
    DROP CONSTRAINT IF EXISTS uq_group_value_per_set,
    DROP CONSTRAINT IF EXISTS fk_group_value_source_q,
    DROP CONSTRAINT IF EXISTS fk_group_value_option,
    DROP CONSTRAINT IF EXISTS fk_group_value_group,
    DROP CONSTRAINT IF EXISTS fk_group_value_set;

ALTER TABLE response
    DROP CONSTRAINT IF EXISTS uq_response_unique_per_set,
    DROP CONSTRAINT IF EXISTS fk_response_option,
    DROP CONSTRAINT IF EXISTS fk_response_question,
    DROP CONSTRAINT IF EXISTS fk_response_set;

ALTER TABLE response_set
    DROP CONSTRAINT IF EXISTS fk_response_set_company;

ALTER TABLE question_to_field_group
    DROP CONSTRAINT IF EXISTS uq_q2fg_question_group,
    DROP CONSTRAINT IF EXISTS fk_q2fg_field_group,
    DROP CONSTRAINT IF EXISTS fk_q2fg_question;

ALTER TABLE field_group
    DROP CONSTRAINT IF EXISTS uq_field_group_key;

ALTER TABLE question_to_screen
    DROP CONSTRAINT IF EXISTS uq_q2s_question_screen,
    DROP CONSTRAINT IF EXISTS fk_q2s_screen,
    DROP CONSTRAINT IF EXISTS fk_q2s_question;

ALTER TABLE answer_option
    DROP CONSTRAINT IF EXISTS fk_answer_option_question;

ALTER TABLE questionnaire_question
    DROP CONSTRAINT IF EXISTS uq_question_external_qid,
    DROP CONSTRAINT IF EXISTS fk_question_transform_rule,
    DROP CONSTRAINT IF EXISTS fk_question_parent;

-- Drop tables (reverse order of creation)
DROP TABLE IF EXISTS generated_document;
DROP TABLE IF EXISTS group_value;
DROP TABLE IF EXISTS response;
DROP TABLE IF EXISTS response_set;
DROP TABLE IF EXISTS question_to_field_group;
DROP TABLE IF EXISTS field_group;
DROP TABLE IF EXISTS question_to_screen;
DROP TABLE IF EXISTS questionnaire_screen;
DROP TABLE IF EXISTS answer_option;
DROP TABLE IF EXISTS questionnaire_question;
DROP TABLE IF EXISTS transformation_rule;
DROP TABLE IF EXISTS company;

-- Drop types
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'apply_mode') THEN
        DROP TYPE apply_mode;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'answer_kind') THEN
        DROP TYPE answer_kind;
    END IF;
END $$;

-- (Optional) extension left installed for other features
