-- Lookup & performance indexes

-- QuestionnaireQuestion
CREATE INDEX IF NOT EXISTS ix_question_answer_type ON questionnaire_question(answer_type);
CREATE INDEX IF NOT EXISTS ix_question_parent ON questionnaire_question(parent_question_id);

-- AnswerOption
CREATE INDEX IF NOT EXISTS ix_answer_option_question ON answer_option(question_id);

-- Response
CREATE INDEX IF NOT EXISTS ix_response_set ON response(response_set_id);
CREATE INDEX IF NOT EXISTS ix_response_question ON response(question_id);
CREATE INDEX IF NOT EXISTS ix_response_option ON response(option_id);

-- GroupValue
CREATE INDEX IF NOT EXISTS ix_group_value_set ON group_value(response_set_id);
CREATE INDEX IF NOT EXISTS ix_group_value_group ON group_value(field_group_id);
CREATE INDEX IF NOT EXISTS ix_group_value_source_q ON group_value(source_question_id);

-- GeneratedDocument
CREATE INDEX IF NOT EXISTS ix_generated_document_set ON generated_document(response_set_id);
CREATE INDEX IF NOT EXISTS ix_generated_document_created ON generated_document(created_at);

-- QuestionToFieldGroup
CREATE INDEX IF NOT EXISTS ix_q2fg_question ON question_to_field_group(question_id);
CREATE INDEX IF NOT EXISTS ix_q2fg_field_group ON question_to_field_group(field_group_id);

-- DocumentBlob
CREATE INDEX IF NOT EXISTS ix_document_blob_sha256 ON document_blob(file_sha256);

-- Placeholder
CREATE INDEX IF NOT EXISTS ix_placeholder_document ON placeholder(document_id);
CREATE INDEX IF NOT EXISTS ix_placeholder_question ON placeholder(question_id);
CREATE INDEX IF NOT EXISTS ix_placeholder_clause ON placeholder(clause_path);

-- EnumOptionPlaceholderLink
CREATE INDEX IF NOT EXISTS ix_eopl_option ON enum_option_placeholder_link(option_id);
CREATE INDEX IF NOT EXISTS ix_eopl_placeholder ON enum_option_placeholder_link(placeholder_id);

-- IdempotencyKey
CREATE INDEX IF NOT EXISTS ix_idempotency_expires ON idempotency_key(expires_at);
