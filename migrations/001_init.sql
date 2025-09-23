-- Generated 2025-09-23T00:35:52.987780Z
-- Epic A (option 1): single handbook, direct placeholder lookup.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enums
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'answer_kind') THEN
        CREATE TYPE answer_kind AS ENUM ('boolean','enum_single','long_text','number','short_string');
    END IF;
END $$;

-- Tables
CREATE TABLE IF NOT EXISTS company (
    company_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name TEXT NOT NULL,
    registered_office_address TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS questionnaire_question (
    question_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_qid TEXT NULL,
    question_text TEXT NOT NULL,
    answer_type answer_kind NOT NULL,
    placeholder_code TEXT NULL,
    mandatory BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS answer_option (
    option_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL,
    value TEXT NOT NULL,
    label TEXT NULL,
    sort_index INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS field_group (
    field_group_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_key TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS question_to_field_group (
    q2fg_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL,
    field_group_id UUID NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS response_set (
    response_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NULL
);

CREATE TABLE IF NOT EXISTS response (
    response_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_set_id UUID NOT NULL,
    question_id UUID NOT NULL,
    value_json JSONB NOT NULL,
    value_text TEXT NULL,
    value_number NUMERIC NULL,
    value_bool BOOLEAN NULL,
    option_id UUID NULL
);

CREATE TABLE IF NOT EXISTS group_value (
    group_value_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_set_id UUID NOT NULL,
    field_group_id UUID NOT NULL,
    value_json JSONB NOT NULL,
    value_text TEXT NULL,
    value_number NUMERIC NULL,
    value_bool BOOLEAN NULL,
    option_id UUID NULL,
    source_question_id UUID NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS generated_document (
    generated_document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_set_id UUID NOT NULL,
    output_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
