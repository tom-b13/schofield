-- Base schema aligned to ERD (simplified for local runs)

-- Central enum types
DO $$ BEGIN
    CREATE TYPE answer_kind AS ENUM ('boolean','enum_single','long_text','number','short_string');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Keep legacy helper tables for local runs
CREATE TABLE IF NOT EXISTS questionnaires (
    questionnaire_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS screens (
    screen_id UUID PRIMARY KEY,
    questionnaire_id UUID NOT NULL REFERENCES questionnaires(questionnaire_id),
    screen_key TEXT NOT NULL,
    title TEXT NOT NULL
);

-- === ERD Entities (canonical snake_case table names) ===

-- Company
CREATE TABLE IF NOT EXISTS company (
    company_id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ,
    legal_name TEXT,
    registered_office_address TEXT,
    updated_at TIMESTAMPTZ
);

-- FieldGroup
CREATE TABLE IF NOT EXISTS field_group (
    field_group_id UUID PRIMARY KEY,
    description TEXT,
    group_key TEXT,
    is_active BOOLEAN,
    label TEXT
);

-- QuestionnaireQuestion
CREATE TABLE IF NOT EXISTS questionnaire_question (
    question_id UUID PRIMARY KEY,
    screen_key TEXT,
    external_qid TEXT,
    question_order INT NOT NULL,
    question_text TEXT NOT NULL,
    answer_type answer_kind NOT NULL,
    mandatory BOOLEAN NOT NULL DEFAULT FALSE,
    placeholder_code TEXT,
    parent_question_id UUID,
    visible_if_value JSONB
);

-- AnswerOption
CREATE TABLE IF NOT EXISTS answer_option (
    option_id UUID PRIMARY KEY,
    question_id UUID NOT NULL,
    value TEXT NOT NULL,
    label TEXT,
    sort_index INT
);

-- ResponseSet
CREATE TABLE IF NOT EXISTS response_set (
    response_set_id UUID PRIMARY KEY,
    company_id UUID,
    created_at TIMESTAMPTZ,
    created_by TEXT
);

-- Response
CREATE TABLE IF NOT EXISTS response (
    response_id UUID PRIMARY KEY,
    response_set_id UUID NOT NULL,
    question_id UUID NOT NULL,
    option_id UUID,
    value_text TEXT,
    value_number NUMERIC,
    value_bool BOOLEAN,
    value_json JSONB,
    answered_at TIMESTAMPTZ DEFAULT now()
);

-- GeneratedDocument
CREATE TABLE IF NOT EXISTS generated_document (
    generated_document_id UUID PRIMARY KEY,
    response_set_id UUID NOT NULL,
    output_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- GroupValue
CREATE TABLE IF NOT EXISTS group_value (
    group_value_id UUID PRIMARY KEY,
    field_group_id UUID,
    option_id UUID,
    response_set_id UUID,
    source_question_id UUID,
    updated_at TIMESTAMPTZ,
    value_bool BOOLEAN,
    value_json JSONB,
    value_number NUMERIC,
    value_text TEXT
);

-- QuestionToFieldGroup
CREATE TABLE IF NOT EXISTS question_to_field_group (
    q2fg_id UUID PRIMARY KEY,
    field_group_id UUID,
    question_id UUID,
    notes TEXT
);

-- Document
CREATE TABLE IF NOT EXISTS document (
    document_id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    order_number INT NOT NULL,
    version INT NOT NULL,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- DocumentBlob
CREATE TABLE IF NOT EXISTS document_blob (
    document_id UUID PRIMARY KEY,
    file_sha256 char(64) NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    storage_url TEXT NOT NULL,
    updated_at TIMESTAMPTZ
);

-- DocumentListState
CREATE TABLE IF NOT EXISTS document_list_state (
    singleton_id SMALLINT PRIMARY KEY,
    list_etag TEXT NOT NULL,
    updated_at TIMESTAMPTZ
);
