-- Core schema for SQLite functional tests
-- Minimal tables to satisfy Epic K contract tests and authoring routes

PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Questionnaires
CREATE TABLE IF NOT EXISTS questionnaire (
  questionnaire_id TEXT PRIMARY KEY,
  name TEXT,
  description TEXT
);

-- Screens
CREATE TABLE IF NOT EXISTS screen (
  screen_id TEXT PRIMARY KEY,
  questionnaire_id TEXT,
  screen_key TEXT,
  title TEXT,
  -- Include screen_order here so ALTER in later migrations can be tolerated
  screen_order INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(questionnaire_id) REFERENCES questionnaire(questionnaire_id)
);

CREATE INDEX IF NOT EXISTS idx_screen_by_qid ON screen(questionnaire_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_screen_qid_order ON screen(questionnaire_id, screen_order);

-- Questions per screen
CREATE TABLE IF NOT EXISTS questionnaire_question (
  question_id TEXT PRIMARY KEY,
  screen_id TEXT,
  screen_key TEXT,
  external_qid TEXT,
  question_order INTEGER NOT NULL DEFAULT 1,
  question_text TEXT,
  answer_kind TEXT,
  mandatory INTEGER NOT NULL DEFAULT 0,
  parent_question_id TEXT,
  visible_if_value TEXT,
  FOREIGN KEY(screen_id) REFERENCES screen(screen_id)
);

CREATE INDEX IF NOT EXISTS idx_question_by_screen_order ON questionnaire_question(screen_key, question_order);

COMMIT;

-- end-of-file

