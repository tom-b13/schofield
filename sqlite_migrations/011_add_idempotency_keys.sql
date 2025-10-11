-- SQLite migration: answer idempotency keys table
-- Purpose: Persist idempotent PATCH results keyed by (response_set_id, question_id, idempotency_key)

CREATE TABLE IF NOT EXISTS answer_idempotency_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_set_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT,
  response_json TEXT,
  etag TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE (response_set_id, question_id, idempotency_key)
);

