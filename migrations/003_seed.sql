-- Minimal seed data for local runs
INSERT INTO questionnaires (questionnaire_id, name)
VALUES ('3c2a1d4e-5678-49ab-9abc-0123456789ab', 'Sample Questionnaire')
ON CONFLICT (questionnaire_id) DO NOTHING;

