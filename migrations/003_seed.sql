-- Minimal seed data for local runs (align with singular table names)
-- Use a separate namespace to avoid clashing with test datasets
-- questionnaire_id distinct from tests' 1111... value
INSERT INTO questionnaire (questionnaire_id, name, description)
VALUES ('f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0', 'SEED-QNR', 'Seeded questionnaire for local runs')
ON CONFLICT (questionnaire_id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description;

-- Seed a default screen for the seeded questionnaire (distinct screen_id/key)
INSERT INTO screen (screen_id, questionnaire_id, screen_key, title, screen_order)
VALUES (
  'e0e0e0e0-e0e0-e0e0-e0e0-e0e0e0e0e0e0',
  'f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0',
  'seed_screen',
  'Seed Screen',
  1
)
ON CONFLICT (screen_id) DO UPDATE SET screen_key=EXCLUDED.screen_key, title=EXCLUDED.title, screen_order=EXCLUDED.screen_order;

-- Seed a canonical question on the seeded screen
-- external_qid uses a distinct token to avoid unique constraint clashes
INSERT INTO questionnaire_question (
    question_id,
    screen_key,
    screen_id,
    external_qid,
    question_order,
    question_text,
    answer_kind,
    mandatory
) VALUES (
    'd0d0d0d0-d0d0-d0d0-d0d0-d0d0d0d0d0d0',
    'seed_screen',
    'e0e0e0e0-e0e0-e0e0-e0e0-e0e0e0e0e0e0',
    'SEED_ENUM_001',
    1,
    'Seed enumerated question',
    'short_string',
    FALSE
) ON CONFLICT (question_id) DO UPDATE SET
    screen_key = EXCLUDED.screen_key,
    screen_id = EXCLUDED.screen_id,
    external_qid = EXCLUDED.external_qid,
    question_order = EXCLUDED.question_order,
    question_text = EXCLUDED.question_text,
    answer_kind = EXCLUDED.answer_kind,
    mandatory = EXCLUDED.mandatory;
