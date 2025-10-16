-- Base schema aligned to ERD (simplified for local runs)

-- Central enum types
DO $$ BEGIN
    CREATE TYPE answer_kind AS ENUM ('boolean','enum_single','long_text','number','short_string');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Keep legacy helper tables for local runs
CREATE TABLE IF NOT EXISTS questionnaire (
    questionnaire_id uuid PRIMARY KEY,
    name text NOT NULL,
    description text
);

CREATE TABLE IF NOT EXISTS screen (
    screen_id uuid PRIMARY KEY,
    questionnaire_id uuid NOT NULL,
    screen_key text NOT NULL,
    title text NOT NULL,
    screen_order int NOT NULL
);

-- === ERD Entities (canonical snake_case table names) ===

-- Company
CREATE TABLE IF NOT EXISTS company (
    company_id uuid PRIMARY KEY,
    created_at timestamptz,
    legal_name text,
    registered_office_address text,
    updated_at timestamptz
);

-- FieldGroup
CREATE TABLE IF NOT EXISTS field_group (
    field_group_id uuid PRIMARY KEY,
    description text,
    group_key text,
    is_active boolean,
    label text
);

-- QuestionnaireQuestion
CREATE TABLE IF NOT EXISTS questionnaire_question (
    question_id uuid PRIMARY KEY,
    screen_key text,
    external_qid text,
    question_order int NOT NULL,
    question_text text NOT NULL,
    answer_kind answer_kind NOT NULL,
    mandatory boolean NOT NULL DEFAULT FALSE,
    placeholder_code text,
    screen_id uuid NOT NULL,
    parent_question_id uuid,
    visible_if_value jsonb
);

-- AnswerOption
CREATE TABLE IF NOT EXISTS answer_option (
    option_id uuid PRIMARY KEY,
    question_id uuid NOT NULL,
    value text NOT NULL,
    label text,
    sort_index int
);

-- ResponseSet
CREATE TABLE IF NOT EXISTS response_set (
    response_set_id uuid PRIMARY KEY,
    company_id uuid,
    created_at timestamptz,
    created_by text,
    name text
);

-- Response
CREATE TABLE IF NOT EXISTS response (
    response_id uuid PRIMARY KEY,
    response_set_id uuid NOT NULL,
    question_id uuid NOT NULL,
    option_id uuid,
    state_version int,
    value_text text,
    value_number numeric,
    value_bool boolean,
    value_json jsonb,
    answered_at timestamptz DEFAULT now()
);

-- GeneratedDocument
CREATE TABLE IF NOT EXISTS generated_document (
    generated_document_id uuid PRIMARY KEY,
    response_set_id uuid NOT NULL,
    output_uri text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- GroupValue
CREATE TABLE IF NOT EXISTS group_value (
    group_value_id uuid PRIMARY KEY,
    field_group_id uuid,
    option_id uuid,
    response_set_id uuid,
    source_question_id uuid,
    updated_at timestamptz,
    value_bool boolean,
    value_json jsonb,
    value_number numeric,
    value_text text
);

-- QuestionToFieldGroup
CREATE TABLE IF NOT EXISTS question_to_field_group (
    q2fg_id uuid PRIMARY KEY,
    field_group_id uuid,
    question_id uuid,
    notes text
);

-- Document
CREATE TABLE IF NOT EXISTS document (
    document_id uuid PRIMARY KEY,
    title text NOT NULL,
    order_number int NOT NULL,
    version int NOT NULL,
    created_at timestamptz,
    updated_at timestamptz
);

-- DocumentBlob
CREATE TABLE IF NOT EXISTS document_blob (
    document_id uuid PRIMARY KEY,
    file_sha256 char(64) NOT NULL,
    filename text NOT NULL,
    mime text NOT NULL,
    byte_size bigint NOT NULL,
    storage_url text NOT NULL,
    updated_at timestamptz
);

-- DocumentListState
CREATE TABLE IF NOT EXISTS document_list_state (
    singleton_id smallint PRIMARY KEY,
    list_etag text NOT NULL,
    updated_at timestamptz
);

-- Placeholder (Epic D)
CREATE TABLE IF NOT EXISTS placeholder (
    placeholder_id uuid PRIMARY KEY,
    document_id uuid,
    question_id uuid,
    clause_path text,
    span_start int,
    span_end int,
    raw_text text,
    transform_id text,
    created_at timestamptz
);

-- EnumOptionPlaceholderLink (Epic D)
CREATE TABLE IF NOT EXISTS enum_option_placeholder_link (
    link_id uuid PRIMARY KEY,
    option_id uuid,
    placeholder_id uuid
);

-- IdempotencyKey (Epic D)
CREATE TABLE IF NOT EXISTS idempotency_key (
    key_id uuid PRIMARY KEY,
    idempotency_key text,
    request_fingerprint char(64),
    created_at timestamptz,
    expires_at timestamptz
);
