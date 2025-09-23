-- Rollbacks (reverse order)
DROP INDEX IF EXISTS ix_generated_document_created;
DROP INDEX IF EXISTS ix_generated_document_set;
DROP INDEX IF EXISTS ix_group_value_source_q;
DROP INDEX IF EXISTS ix_group_value_group;
DROP INDEX IF EXISTS ix_group_value_set;
DROP INDEX IF EXISTS ix_response_option;
DROP INDEX IF EXISTS ix_response_question;
DROP INDEX IF EXISTS ix_response_set;
DROP INDEX IF EXISTS ix_answer_option_question;
DROP INDEX IF EXISTS ix_question_answer_type;
DROP INDEX IF EXISTS uq_question_placeholder_code;

ALTER TABLE group_value
    DROP CONSTRAINT IF EXISTS fk_group_value_source_q,
    DROP CONSTRAINT IF EXISTS fk_group_value_option,
    DROP CONSTRAINT IF EXISTS fk_group_value_group,
    DROP CONSTRAINT IF EXISTS fk_group_value_set,
    DROP CONSTRAINT IF EXISTS uq_group_value_per_set;

ALTER TABLE response
    DROP CONSTRAINT IF EXISTS fk_response_option,
    DROP CONSTRAINT IF EXISTS fk_response_question,
    DROP CONSTRAINT IF EXISTS fk_response_set,
    DROP CONSTRAINT IF EXISTS uq_response_set_question;

ALTER TABLE response_set
    DROP CONSTRAINT IF EXISTS fk_response_set_company;

ALTER TABLE question_to_field_group
    DROP CONSTRAINT IF EXISTS uq_q2fg_question_group,
    DROP CONSTRAINT IF EXISTS fk_q2fg_field_group,
    DROP CONSTRAINT IF EXISTS fk_q2fg_question;

ALTER TABLE answer_option
    DROP CONSTRAINT IF EXISTS uq_answer_option_question_value,
    DROP CONSTRAINT IF EXISTS fk_answer_option_question;

ALTER TABLE questionnaire_question
    DROP CONSTRAINT IF EXISTS uq_question_external_qid;

DROP TABLE IF EXISTS generated_document;
DROP TABLE IF EXISTS group_value;
DROP TABLE IF EXISTS response;
DROP TABLE IF EXISTS response_set;
DROP TABLE IF EXISTS question_to_field_group;
DROP TABLE IF EXISTS field_group;
DROP TABLE IF EXISTS answer_option;
DROP TABLE IF EXISTS questionnaire_question;
DROP TABLE IF EXISTS company;

DROP TYPE IF EXISTS answer_kind;
