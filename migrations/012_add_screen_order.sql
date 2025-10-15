-- EPIC G: Add screen_order to screens for contiguous ordering per questionnaire
ALTER TABLE screens
    ADD COLUMN IF NOT EXISTS screen_order INT NOT NULL;

