-- Ensure ENUM label 'short_string' exists on type answer_kind (idempotent)
-- Clarke directive: add missing enum values in a safe, repeatable manner.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = 'answer_kind'
          AND e.enumlabel = 'short_string'
    ) THEN
        ALTER TYPE answer_kind ADD VALUE 'short_string';
    END IF;
END
$$;

