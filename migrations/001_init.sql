-- Generated 2025-09-22T23:17:51.080676Z
-- Epic A (option 1): single handbook, no template tables.
-- Create required extension(s)
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

-- Enums
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'answer_kind') THEN
        CREATE TYPE answer_kind AS ENUM ('short_string','long_text','boolean','enum','number');
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'apply_mode') THEN
        CREATE TYPE apply_mode AS ENUM ('reference','copy_on_first_set','prefer_group');
    END IF;
END $$;

-- Tables (PKs inline, FKs/uniques/indexes added in 002/003)
CREATE TABLE IF NOT EXISTS company (
    company_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name TEXT NOT NULL,
    registered_office_address TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS transformation_rule (
    rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NULL,
    expression JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS questionnaire_question (
    question_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_qid TEXT NULL,
    question_text TEXT NOT NULL,
    answer_type answer_kind NOT NULL,
    section TEXT NULL,
    is_conditional BOOLEAN NOT NULL DEFAULT FALSE,
    parent_question_id UUID NULL,
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    -- option 1 additions:
    placeholder_code TEXT NULL,
    mandatory BOOLEAN NOT NULL DEFAULT FALSE,
    apply_mode apply_mode NOT NULL DEFAULT 'reference',
    transform_rule_id UUID NULL
);

CREATE TABLE IF NOT EXISTS answer_option (
    option_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL,
    value TEXT NOT NULL,
    label TEXT NULL,
    sort_index INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS questionnaire_screen (
    screen_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NULL,
    version INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_index INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS question_to_screen (
    q2s_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL,
    screen_id UUID NOT NULL,
    sort_index INT NOT NULL DEFAULT 0,
    required BOOLEAN NOT NULL DEFAULT FALSE,
    visible_when JSONB NULL,
    display_hint TEXT NULL,
    input_component TEXT NULL,
    validation JSONB NULL
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
    apply_mode apply_mode NOT NULL,
    notes TEXT NULL
);

CREATE TABLE IF NOT EXISTS response_set (
    response_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NULL,
    template_lock JSONB NULL
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

-- Simplified generated_document (no template/doc_kind)
CREATE TABLE IF NOT EXISTS generated_document (
    generated_document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_set_id UUID NOT NULL,
    output_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
