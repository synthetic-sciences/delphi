-- Migration 016: Enable RLS on rate_limits table
--
-- The rate_limits table was created without RLS (migration 003).
-- It's only accessed via the check_rate_limit() RPC function (SECURITY DEFINER),
-- so no direct access policies are needed — just enable RLS to block direct reads/writes.
--
-- Run with: psql $DATABASE_URL -f migrations/016_rate_limits_rls.sql
-- Or paste into Supabase SQL Editor.

ALTER TABLE public.rate_limits ENABLE ROW LEVEL SECURITY;

-- No policies = no direct access from anon/authenticated roles.
-- The check_rate_limit() function runs as SECURITY DEFINER and bypasses RLS.

DO $$
BEGIN
    RAISE NOTICE 'Migration 016 complete: RLS enabled on rate_limits (no direct access policies).';
END $$;
