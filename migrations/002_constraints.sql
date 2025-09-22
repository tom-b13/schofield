-- migrations/002_constraints.sql
-- Foreign keys, uniques
-- FK: QuestionnaireQuestion.parent_question_id -> QuestionnaireQuestion
ALTER TABLE QuestionnaireQuestion
  ADD CONSTRAINT fk_question_parent
  FOREIGN KEY (parent_question_id) REFERENCES QuestionnaireQuestion(question_id);

-- AnswerOption
ALTER TABLE AnswerOption
  ADD CONSTRAINT fk_answeroption_question FOREIGN KEY (question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE AnswerOption
  ADD CONSTRAINT uq_answeroption_question_value UNIQUE (question_id, value);

-- ContractTemplate
ALTER TABLE ContractTemplate
  ADD CONSTRAINT uq_contracttemplate_name_version UNIQUE (name, version);

-- TemplatePlaceholder
ALTER TABLE TemplatePlaceholder
  ADD CONSTRAINT fk_tplph_document FOREIGN KEY (document_id) REFERENCES ContractTemplate(contract_template_id);
ALTER TABLE TemplatePlaceholder
  ADD CONSTRAINT uq_tplph_doc_entity_field UNIQUE (document_type, document_id, entity_name, field_name);

-- QuestionToPlaceholder
ALTER TABLE QuestionToPlaceholder
  ADD CONSTRAINT fk_q2p_question FOREIGN KEY (question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE QuestionToPlaceholder
  ADD CONSTRAINT fk_q2p_placeholder FOREIGN KEY (placeholder_id) REFERENCES TemplatePlaceholder(placeholder_id);
ALTER TABLE QuestionToPlaceholder
  ADD CONSTRAINT fk_q2p_rule FOREIGN KEY (transformation_rule_id) REFERENCES TransformationRule(rule_id);
ALTER TABLE QuestionToPlaceholder
  ADD CONSTRAINT uq_q2p_question_placeholder UNIQUE (question_id, placeholder_id);

-- QuestionToScreen
ALTER TABLE QuestionToScreen
  ADD CONSTRAINT fk_q2s_question FOREIGN KEY (question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE QuestionToScreen
  ADD CONSTRAINT fk_q2s_screen FOREIGN KEY (screen_id) REFERENCES QuestionnaireScreen(screen_id);
ALTER TABLE QuestionToScreen
  ADD CONSTRAINT uq_q2s_question_screen UNIQUE (question_id, screen_id);

-- FieldGroup
ALTER TABLE FieldGroup
  ADD CONSTRAINT uq_fieldgroup_group_key UNIQUE (group_key);

-- QuestionToFieldGroup
ALTER TABLE QuestionToFieldGroup
  ADD CONSTRAINT fk_q2fg_question FOREIGN KEY (question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE QuestionToFieldGroup
  ADD CONSTRAINT fk_q2fg_group FOREIGN KEY (field_group_id) REFERENCES FieldGroup(field_group_id);
ALTER TABLE QuestionToFieldGroup
  ADD CONSTRAINT uq_q2fg_question_group UNIQUE (question_id, field_group_id);

-- GroupValue
ALTER TABLE GroupValue
  ADD CONSTRAINT fk_groupvalue_responseset FOREIGN KEY (response_set_id) REFERENCES ResponseSet(response_set_id);
ALTER TABLE GroupValue
  ADD CONSTRAINT fk_groupvalue_group FOREIGN KEY (field_group_id) REFERENCES FieldGroup(field_group_id);
ALTER TABLE GroupValue
  ADD CONSTRAINT fk_groupvalue_option FOREIGN KEY (option_id) REFERENCES AnswerOption(option_id);
ALTER TABLE GroupValue
  ADD CONSTRAINT fk_groupvalue_source_question FOREIGN KEY (source_question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE GroupValue
  ADD CONSTRAINT uq_groupvalue_responseset_group UNIQUE (response_set_id, field_group_id);

-- ResponseSet
ALTER TABLE ResponseSet
  ADD CONSTRAINT fk_responseset_company FOREIGN KEY (company_id) REFERENCES Company(company_id);

-- Response
ALTER TABLE Response
  ADD CONSTRAINT fk_response_responseset FOREIGN KEY (response_set_id) REFERENCES ResponseSet(response_set_id);
ALTER TABLE Response
  ADD CONSTRAINT fk_response_question FOREIGN KEY (question_id) REFERENCES QuestionnaireQuestion(question_id);
ALTER TABLE Response
  ADD CONSTRAINT fk_response_option FOREIGN KEY (option_id) REFERENCES AnswerOption(option_id);
ALTER TABLE Response
  ADD CONSTRAINT uq_response_responseset_question UNIQUE (response_set_id, question_id);

-- ComputedPlaceholderValue
ALTER TABLE ComputedPlaceholderValue
  ADD CONSTRAINT fk_cpv_responseset FOREIGN KEY (response_set_id) REFERENCES ResponseSet(response_set_id);
ALTER TABLE ComputedPlaceholderValue
  ADD CONSTRAINT fk_cpv_placeholder FOREIGN KEY (placeholder_id) REFERENCES TemplatePlaceholder(placeholder_id);
ALTER TABLE ComputedPlaceholderValue
  ADD CONSTRAINT fk_cpv_rule FOREIGN KEY (rule_id) REFERENCES TransformationRule(rule_id);
ALTER TABLE ComputedPlaceholderValue
  ADD CONSTRAINT uq_cpv_responseset_placeholder UNIQUE (response_set_id, placeholder_id);

-- GeneratedDocument
ALTER TABLE GeneratedDocument
  ADD CONSTRAINT fk_gendoc_responseset FOREIGN KEY (response_set_id) REFERENCES ResponseSet(response_set_id);
ALTER TABLE GeneratedDocument
  ADD CONSTRAINT fk_gendoc_template FOREIGN KEY (document_id) REFERENCES ContractTemplate(contract_template_id);
