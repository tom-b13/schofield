-- EPIC G: Add screen_order to screens for contiguous ordering per questionnaire
-- Make the migration safe for existing rows: add nullable, backfill, then enforce NOT NULL
ALTER TABLE screen
    ADD COLUMN IF NOT EXISTS screen_order INT;

UPDATE screen
SET screen_order = 0
WHERE screen_order IS NULL;

ALTER TABLE screen
    ALTER COLUMN screen_order SET NOT NULL;
