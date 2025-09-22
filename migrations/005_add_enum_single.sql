-- 2025-09-22T23:28:26.947596Z
-- Patch: add enum_single to answer_kind
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_enum e ON t.oid = e.enumtypid
        WHERE t.typname = 'answer_kind' AND e.enumlabel = 'enum_single'
    ) THEN
        ALTER TYPE answer_kind ADD VALUE 'enum_single';
    END IF;
END $$;
