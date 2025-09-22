-- migrations/001_init.sql
-- Initial schema creation (tables only, PKs inline; FKs/UNIQUES/INDEXES in later migrations)
CREATE TABLE IF NOT EXISTS Company (
  company_id UUID PRIMARY KEY,
  legal_name TEXT NOT NULL,
  registered_office_address TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS QuestionnaireQuestion (
  question_id UUID PRIMARY KEY,
  external_qid TEXT UNIQUE,
  question_text TEXT NOT NULL,
  answer_type TEXT NOT NULL,
  section TEXT,
  is_conditional BOOLEAN DEFAULT FALSE,
  parent_question_id UUID,
  version INT DEFAULT 1,
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS AnswerOption (
  option_id UUID PRIMARY KEY,
  question_id UUID NOT NULL,
  value TEXT NOT NULL,
  label TEXT NOT NULL,
  sort_index INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ContractTemplate (
  contract_template_id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  version INT NOT NULL,
  doc_uri TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TemplatePlaceholder (
  placeholder_id UUID PRIMARY KEY,
  document_type TEXT NOT NULL,
  document_id UUID NOT NULL,
  entity_name TEXT NOT NULL,
  field_name TEXT NOT NULL,
  placeholder_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TransformationRule (
  rule_id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  expression JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS QuestionToPlaceholder (
  q2p_id UUID PRIMARY KEY,
  question_id UUID NOT NULL,
  placeholder_id UUID NOT NULL,
  transformation_rule_id UUID,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS QuestionnaireScreen (
  screen_id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  version INT DEFAULT 1,
  is_active BOOLEAN DEFAULT TRUE,
  sort_index INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS QuestionToScreen (
  q2s_id UUID PRIMARY KEY,
  question_id UUID NOT NULL,
  screen_id UUID NOT NULL,
  sort_index INT DEFAULT 0,
  required BOOLEAN DEFAULT FALSE,
  visible_when JSONB,
  display_hint TEXT,
  input_component TEXT,
  validation JSONB
);

-- NEW: Field Grouping
CREATE TABLE IF NOT EXISTS FieldGroup (
  field_group_id UUID PRIMARY KEY,
  group_key TEXT NOT NULL,
  label TEXT NOT NULL,
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS QuestionToFieldGroup (
  q2fg_id UUID PRIMARY KEY,
  question_id UUID NOT NULL,
  field_group_id UUID NOT NULL,
  apply_mode TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS GroupValue (
  group_value_id UUID PRIMARY KEY,
  response_set_id UUID NOT NULL,
  field_group_id UUID NOT NULL,
  value_json JSONB NOT NULL,
  value_text TEXT,
  value_number NUMERIC,
  value_bool BOOLEAN,
  option_id UUID,
  source_question_id UUID,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ResponseSet (
  response_set_id UUID PRIMARY KEY,
  company_id UUID NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by TEXT,
  template_lock JSONB
);

CREATE TABLE IF NOT EXISTS Response (
  response_id UUID PRIMARY KEY,
  response_set_id UUID NOT NULL,
  question_id UUID NOT NULL,
  value_json JSONB NOT NULL,
  value_text TEXT,
  value_number NUMERIC,
  value_bool BOOLEAN,
  option_id UUID
);

CREATE TABLE IF NOT EXISTS ComputedPlaceholderValue (
  cpv_id UUID PRIMARY KEY,
  response_set_id UUID NOT NULL,
  placeholder_id UUID NOT NULL,
  computed_json JSONB NOT NULL,
  rule_id UUID,
  computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS GeneratedDocument (
  generated_document_id UUID PRIMARY KEY,
  response_set_id UUID NOT NULL,
  document_type TEXT NOT NULL,
  document_id UUID NOT NULL,
  output_uri TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
