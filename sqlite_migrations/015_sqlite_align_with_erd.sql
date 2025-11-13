-- Align SQLite schema with docs/erd_spec.json and application code
-- Idempotent, safe to re-run. Focused on minimal tables/columns used by tests.

PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- 1) Ensure response_set exists (used by existence checks and FKs)
CREATE TABLE IF NOT EXISTS response_set (
  response_set_id TEXT PRIMARY KEY,
  company_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_response_set_id ON response_set(response_set_id);

-- 2) Ensure questionnaire_question has placeholder_code column
-- SQLite does not support IF NOT EXISTS for ADD COLUMN; allow duplicate-column error at runtime.
ALTER TABLE questionnaire_question ADD COLUMN placeholder_code TEXT;

-- 3) Ensure answer_option exists for enum options
CREATE TABLE IF NOT EXISTS answer_option (
  option_id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  value TEXT NOT NULL,
  label TEXT,
  sort_index INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(question_id) REFERENCES questionnaire_question(question_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_answer_option_question_value
  ON answer_option (question_id, value);
CREATE INDEX IF NOT EXISTS ix_answer_option_question
  ON answer_option (question_id);

COMMIT;

-- end-of-file

