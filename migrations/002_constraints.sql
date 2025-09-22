-- Foreign keys
ALTER TABLE questionnaire_question
    ADD CONSTRAINT fk_question_parent
        FOREIGN KEY (parent_question_id) REFERENCES questionnaire_question(question_id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_question_transform_rule
        FOREIGN KEY (transform_rule_id) REFERENCES transformation_rule(rule_id) ON DELETE SET NULL;

ALTER TABLE answer_option
    ADD CONSTRAINT fk_answer_option_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id) ON DELETE CASCADE;

ALTER TABLE question_to_screen
    ADD CONSTRAINT fk_q2s_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_q2s_screen
        FOREIGN KEY (screen_id) REFERENCES questionnaire_screen(screen_id) ON DELETE CASCADE,
    ADD CONSTRAINT uq_q2s_question_screen UNIQUE (question_id, screen_id);

ALTER TABLE field_group
    ADD CONSTRAINT uq_field_group_key UNIQUE (group_key);

ALTER TABLE question_to_field_group
    ADD CONSTRAINT fk_q2fg_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_q2fg_field_group
        FOREIGN KEY (field_group_id) REFERENCES field_group(field_group_id) ON DELETE CASCADE,
    ADD CONSTRAINT uq_q2fg_question_group UNIQUE (question_id, field_group_id);

ALTER TABLE response_set
    ADD CONSTRAINT fk_response_set_company
        FOREIGN KEY (company_id) REFERENCES company(company_id) ON DELETE CASCADE;

ALTER TABLE response
    ADD CONSTRAINT fk_response_set
        FOREIGN KEY (response_set_id) REFERENCES response_set(response_set_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_response_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_response_option
        FOREIGN KEY (option_id) REFERENCES answer_option(option_id) ON DELETE SET NULL,
    ADD CONSTRAINT uq_response_unique_per_set UNIQUE (response_set_id, question_id);

ALTER TABLE group_value
    ADD CONSTRAINT fk_group_value_set
        FOREIGN KEY (response_set_id) REFERENCES response_set(response_set_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_group_value_group
        FOREIGN KEY (field_group_id) REFERENCES field_group(field_group_id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_group_value_option
        FOREIGN KEY (option_id) REFERENCES answer_option(option_id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_group_value_source_q
        FOREIGN KEY (source_question_id) REFERENCES questionnaire_question(question_id) ON DELETE SET NULL,
    ADD CONSTRAINT uq_group_value_per_set UNIQUE (response_set_id, field_group_id);

-- Unique: external_qid unique if provided
ALTER TABLE questionnaire_question
    ADD CONSTRAINT uq_question_external_qid UNIQUE (external_qid);

-- Partial unique: placeholder_code must be unique when provided
-- (Postgres: enforce with a partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS uq_question_placeholder_code
    ON questionnaire_question(placeholder_code)
    WHERE placeholder_code IS NOT NULL;
