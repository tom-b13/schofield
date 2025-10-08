-- Rollbacks (strict reverse of 003 -> 002 -> 001 creation order)

-- 003: Indexes (drop in exact reverse of appearance in migrations/003_indexes.sql)
DROP INDEX IF EXISTS ix_idempotency_expires;
DROP INDEX IF EXISTS ix_eopl_placeholder;
DROP INDEX IF EXISTS ix_eopl_option;
DROP INDEX IF EXISTS ix_placeholder_clause;
DROP INDEX IF EXISTS ix_placeholder_question;
DROP INDEX IF EXISTS ix_placeholder_document;
DROP INDEX IF EXISTS ix_document_blob_sha256;
DROP INDEX IF EXISTS ix_q2fg_field_group;
DROP INDEX IF EXISTS ix_q2fg_question;
DROP INDEX IF EXISTS ix_generated_document_created;
DROP INDEX IF EXISTS ix_generated_document_set;
DROP INDEX IF EXISTS ix_group_value_source_q;
DROP INDEX IF EXISTS ix_group_value_group;
DROP INDEX IF EXISTS ix_group_value_set;
DROP INDEX IF EXISTS ix_response_option;
DROP INDEX IF EXISTS ix_response_question;
DROP INDEX IF EXISTS ix_response_set;
DROP INDEX IF EXISTS ix_answer_option_question;
DROP INDEX IF EXISTS ix_question_parent;
DROP INDEX IF EXISTS ix_question_answer_type;

-- 002: Constraints and named uniques (reverse of migrations/002_constraints.sql)
ALTER TABLE idempotency_key
    DROP CONSTRAINT IF EXISTS uq_idempotency_key_unique;
ALTER TABLE placeholder
    DROP CONSTRAINT IF EXISTS uq_placeholder_doc_clause_span;
ALTER TABLE enum_option_placeholder_link
    DROP CONSTRAINT IF EXISTS uq_eopl_option_unique;
ALTER TABLE enum_option_placeholder_link
    DROP CONSTRAINT IF EXISTS fk_eopl_placeholder,
    DROP CONSTRAINT IF EXISTS fk_eopl_option;
ALTER TABLE placeholder
    DROP CONSTRAINT IF EXISTS fk_placeholder_question,
    DROP CONSTRAINT IF EXISTS fk_placeholder_document;
ALTER TABLE document
    DROP CONSTRAINT IF EXISTS uq_document_order_number;
ALTER TABLE document_blob
    DROP CONSTRAINT IF EXISTS fk_document_blob_document;
DROP INDEX IF EXISTS uq_question_placeholder_code;

ALTER TABLE questionnaire_question
    DROP CONSTRAINT IF EXISTS uq_question_external_qid,
    DROP CONSTRAINT IF EXISTS fk_question_parent_question;

ALTER TABLE group_value
    DROP CONSTRAINT IF EXISTS uq_group_value_per_set,
    DROP CONSTRAINT IF EXISTS fk_group_value_source_q,
    DROP CONSTRAINT IF EXISTS fk_group_value_set,
    DROP CONSTRAINT IF EXISTS fk_group_value_option,
    DROP CONSTRAINT IF EXISTS fk_group_value_group;

ALTER TABLE response
    DROP CONSTRAINT IF EXISTS uq_response_set_question,
    DROP CONSTRAINT IF EXISTS fk_response_set,
    DROP CONSTRAINT IF EXISTS fk_response_question,
    DROP CONSTRAINT IF EXISTS fk_response_option;

ALTER TABLE generated_document
    DROP CONSTRAINT IF EXISTS fk_generated_document_set;

ALTER TABLE response_set
    DROP CONSTRAINT IF EXISTS fk_response_set_company;

ALTER TABLE question_to_field_group
    DROP CONSTRAINT IF EXISTS uq_q2fg_question_group,
    DROP CONSTRAINT IF EXISTS fk_q2fg_question,
    DROP CONSTRAINT IF EXISTS fk_q2fg_field_group;

ALTER TABLE answer_option
    DROP CONSTRAINT IF EXISTS uq_answer_option_question_value,
    DROP CONSTRAINT IF EXISTS fk_answer_option_question;

-- 001: Tables (reverse of creation order in migrations/001_init.sql)
DROP TABLE IF EXISTS idempotency_key;
DROP TABLE IF EXISTS enum_option_placeholder_link;
DROP TABLE IF EXISTS placeholder;
DROP TABLE IF EXISTS document_list_state;
DROP TABLE IF EXISTS document_blob;
DROP TABLE IF EXISTS document;
DROP TABLE IF EXISTS question_to_field_group;
DROP TABLE IF EXISTS group_value;
DROP TABLE IF EXISTS generated_document;
DROP TABLE IF EXISTS response;
DROP TABLE IF EXISTS response_set;
DROP TABLE IF EXISTS answer_option;
DROP TABLE IF EXISTS questionnaire_question;
DROP TABLE IF EXISTS field_group;
DROP TABLE IF EXISTS company;
DROP TABLE IF EXISTS screens;
DROP TABLE IF EXISTS questionnaires;

-- Enum types
DROP TYPE IF EXISTS answer_kind;
