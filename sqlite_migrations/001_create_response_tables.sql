-- SQLite schema for Epic E — Response ingestion
-- Creates core tables used by repository layers in local dev/CI.

PRAGMA foreign_keys = ON;

-- Screens catalog used by repository_screens.get_screen_metadata
CREATE TABLE IF NOT EXISTS screens (
  screen_id TEXT PRIMARY KEY,            -- UUID as TEXT
  screen_key TEXT NOT NULL UNIQUE,
  title TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_screens_screen_key ON screens(screen_key);

-- Questionnaire questions bound to a screen
CREATE TABLE IF NOT EXISTS questionnaire_question (
  question_id TEXT PRIMARY KEY,          -- UUID as TEXT
  external_qid TEXT,
  question_text TEXT,
  answer_type TEXT,                      -- e.g., number, boolean, enum_single, short_string
  mandatory INTEGER DEFAULT 0,
  question_order INTEGER DEFAULT 0,
  screen_key TEXT NOT NULL,
  screen_id TEXT,
  parent_question_id TEXT,
  visible_if_value TEXT,
  FOREIGN KEY(screen_key) REFERENCES screens(screen_key)
);
CREATE INDEX IF NOT EXISTS idx_question_by_screen_key ON questionnaire_question(screen_key);

-- Responses saved per (response_set_id, question_id)
CREATE TABLE IF NOT EXISTS response (
  response_id TEXT PRIMARY KEY,          -- UUID as TEXT
  response_set_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  option_id TEXT,
  value_text TEXT,
  value_number REAL,
  value_bool INTEGER,
  value_json TEXT,
  answered_at TEXT,
  UNIQUE(response_set_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_response_by_rs_q ON response(response_set_id, question_id);

