-- Constraints and unique indexes (named) — aligned to ERD

-- 1) AnswerOption FKs/Uniques
ALTER TABLE answer_option
    ADD CONSTRAINT fk_answer_option_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id);
ALTER TABLE answer_option
    ADD CONSTRAINT uq_answer_option_question_value
        UNIQUE (question_id, value);

-- 2) QuestionToFieldGroup FKs/Uniques
ALTER TABLE question_to_field_group
    ADD CONSTRAINT fk_q2fg_field_group
        FOREIGN KEY (field_group_id) REFERENCES field_group(field_group_id);
ALTER TABLE question_to_field_group
    ADD CONSTRAINT fk_q2fg_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id);
ALTER TABLE question_to_field_group
    ADD CONSTRAINT uq_q2fg_question_group
        UNIQUE (question_id, field_group_id);

-- 3) ResponseSet FKs
ALTER TABLE response_set
    ADD CONSTRAINT fk_response_set_company
        FOREIGN KEY (company_id) REFERENCES company(company_id);

-- 4) GeneratedDocument FKs
ALTER TABLE generated_document
    ADD CONSTRAINT fk_generated_document_set
        FOREIGN KEY (response_set_id) REFERENCES response_set(response_set_id);

-- 5) Response FKs/Uniques
ALTER TABLE response
    ADD CONSTRAINT fk_response_option
        FOREIGN KEY (option_id) REFERENCES answer_option(option_id);
ALTER TABLE response
    ADD CONSTRAINT fk_response_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id);
ALTER TABLE response
    ADD CONSTRAINT fk_response_set
        FOREIGN KEY (response_set_id) REFERENCES response_set(response_set_id);
ALTER TABLE response
    ADD CONSTRAINT uq_response_set_question
        UNIQUE (response_set_id, question_id);

-- 6) GroupValue FKs/Uniques
ALTER TABLE group_value
    ADD CONSTRAINT fk_group_value_group
        FOREIGN KEY (field_group_id) REFERENCES field_group(field_group_id);
ALTER TABLE group_value
    ADD CONSTRAINT fk_group_value_option
        FOREIGN KEY (option_id) REFERENCES answer_option(option_id);
ALTER TABLE group_value
    ADD CONSTRAINT fk_group_value_set
        FOREIGN KEY (response_set_id) REFERENCES response_set(response_set_id);
ALTER TABLE group_value
    ADD CONSTRAINT fk_group_value_source_q
        FOREIGN KEY (source_question_id) REFERENCES questionnaire_question(question_id);
ALTER TABLE group_value
    ADD CONSTRAINT uq_group_value_per_set
        UNIQUE (response_set_id, field_group_id);

-- 7) QuestionnaireQuestion FKs/Uniques
ALTER TABLE questionnaire_question
    ADD CONSTRAINT fk_question_parent_question
        FOREIGN KEY (parent_question_id) REFERENCES questionnaire_question(question_id);
ALTER TABLE questionnaire_question
    ADD CONSTRAINT uq_question_external_qid
        UNIQUE (external_qid);

-- 8) Partial unique index for placeholder code (deterministic lookup contract)
CREATE UNIQUE INDEX IF NOT EXISTS uq_question_placeholder_code
    ON questionnaire_question (placeholder_code)
    WHERE placeholder_code IS NOT NULL;


-- 9) Document FKs
ALTER TABLE document_blob
    ADD CONSTRAINT fk_document_blob_document
        FOREIGN KEY (document_id) REFERENCES document(document_id) ON DELETE CASCADE;

-- 10) Document uniques
ALTER TABLE document
    ADD CONSTRAINT uq_document_order_number
        UNIQUE (order_number);

-- 11) Placeholder FKs
ALTER TABLE placeholder
    ADD CONSTRAINT fk_placeholder_document
        FOREIGN KEY (document_id) REFERENCES document(document_id) ON DELETE CASCADE;
ALTER TABLE placeholder
    ADD CONSTRAINT fk_placeholder_question
        FOREIGN KEY (question_id) REFERENCES questionnaire_question(question_id);

-- 12) EnumOptionPlaceholderLink FKs
ALTER TABLE enum_option_placeholder_link
    ADD CONSTRAINT fk_eopl_option
        FOREIGN KEY (option_id) REFERENCES answer_option(option_id) ON DELETE CASCADE;
ALTER TABLE enum_option_placeholder_link
    ADD CONSTRAINT fk_eopl_placeholder
        FOREIGN KEY (placeholder_id) REFERENCES placeholder(placeholder_id) ON DELETE CASCADE;

-- EnumOptionPlaceholderLink uniques
ALTER TABLE enum_option_placeholder_link
    ADD CONSTRAINT uq_eopl_option_unique
        UNIQUE (option_id);

-- 13) Placeholder & IdempotencyKey uniques
ALTER TABLE placeholder
    ADD CONSTRAINT uq_placeholder_doc_clause_span
        UNIQUE (document_id, clause_path, span_start, span_end);
ALTER TABLE idempotency_key
    ADD CONSTRAINT uq_idempotency_key_unique
        UNIQUE (idempotency_key);
