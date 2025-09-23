-- 2025-09-23T00:35:52.987780Z
-- Patch: add enum_single to answer_kind (safe if already present)
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'answer_kind')
       AND NOT EXISTS (
           SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
           WHERE t.typname = 'answer_kind' AND e.enumlabel = 'enum_single'
       )
    THEN
        ALTER TYPE answer_kind ADD VALUE 'enum_single';
    END IF;
END $$;
