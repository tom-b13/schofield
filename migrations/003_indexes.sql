-- QuestionnaireQuestion
CREATE INDEX IF NOT EXISTS ix_question_section ON questionnaire_question(section);
CREATE INDEX IF NOT EXISTS ix_question_answer_type ON questionnaire_question(answer_type);

-- AnswerOption
CREATE UNIQUE INDEX IF NOT EXISTS uq_answer_option_question_value ON answer_option(question_id, value);
CREATE INDEX IF NOT EXISTS ix_answer_option_question ON answer_option(question_id);

-- QuestionnaireScreen
CREATE INDEX IF NOT EXISTS ix_screen_sort ON questionnaire_screen(sort_index);
CREATE INDEX IF NOT EXISTS ix_screen_active ON questionnaire_screen(is_active);

-- QuestionToScreen
CREATE INDEX IF NOT EXISTS ix_q2s_screen_sort ON question_to_screen(screen_id, sort_index);
CREATE INDEX IF NOT EXISTS ix_q2s_question ON question_to_screen(question_id);

-- FieldGroup
CREATE INDEX IF NOT EXISTS ix_field_group_key ON field_group(group_key);

-- QuestionToFieldGroup
CREATE INDEX IF NOT EXISTS ix_q2fg_question ON question_to_field_group(question_id);
CREATE INDEX IF NOT EXISTS ix_q2fg_group ON question_to_field_group(field_group_id);

-- ResponseSet
CREATE INDEX IF NOT EXISTS ix_response_set_company ON response_set(company_id);
CREATE INDEX IF NOT EXISTS ix_response_set_created_at ON response_set(created_at);

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
