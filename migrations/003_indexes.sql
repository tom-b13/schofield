-- migrations/003_indexes.sql
-- Common foreign key and lookup indexes
CREATE INDEX IF NOT EXISTS idx_answeroption_question ON AnswerOption(question_id);
CREATE INDEX IF NOT EXISTS idx_templateplaceholder_document ON TemplatePlaceholder(document_id);
CREATE INDEX IF NOT EXISTS idx_q2p_question ON QuestionToPlaceholder(question_id);
CREATE INDEX IF NOT EXISTS idx_q2p_placeholder ON QuestionToPlaceholder(placeholder_id);

CREATE INDEX IF NOT EXISTS idx_questionscreen_screen ON QuestionToScreen(screen_id, sort_index);
CREATE INDEX IF NOT EXISTS idx_questionscreen_question ON QuestionToScreen(question_id);

CREATE INDEX IF NOT EXISTS idx_fieldgroup_group_key ON FieldGroup(group_key);
CREATE INDEX IF NOT EXISTS idx_q2fg_question ON QuestionToFieldGroup(question_id);
CREATE INDEX IF NOT EXISTS idx_q2fg_group ON QuestionToFieldGroup(field_group_id);

CREATE INDEX IF NOT EXISTS idx_groupvalue_responseset ON GroupValue(response_set_id);
CREATE INDEX IF NOT EXISTS idx_groupvalue_group ON GroupValue(field_group_id);
CREATE INDEX IF NOT EXISTS idx_groupvalue_source_question ON GroupValue(source_question_id);

CREATE INDEX IF NOT EXISTS idx_responseset_company ON ResponseSet(company_id);
CREATE INDEX IF NOT EXISTS idx_response_responseset ON Response(response_set_id);
CREATE INDEX IF NOT EXISTS idx_response_question ON Response(question_id);
CREATE INDEX IF NOT EXISTS idx_response_option ON Response(option_id);

CREATE INDEX IF NOT EXISTS idx_gendoc_responseset ON GeneratedDocument(response_set_id);
CREATE INDEX IF NOT EXISTS idx_gendoc_document ON GeneratedDocument(document_id);
