-- Migration 003: Database-backed rate limiting
--
-- Replaces the in-memory rate_limit_store dict with a Supabase table
-- and RPC function for atomic check-and-increment.
--
-- Benefits:
--   - Persists across deploys/restarts
--   - Shared across all Gunicorn workers and API instances
--   - Atomic via PostgreSQL UPSERT
--
-- Run with: psql $DATABASE_URL -f migrations/003_rate_limits.sql
-- Or paste into Supabase SQL Editor.

-- 1. Create the rate_limits table (fixed-window counters)
CREATE TABLE IF NOT EXISTS rate_limits (
    api_key_hash TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (api_key_hash, window_start)
);

-- 2. Create the RPC function for atomic rate limit checking
CREATE OR REPLACE FUNCTION check_rate_limit(
    p_key_hash TEXT,
    p_limit INTEGER DEFAULT 60,
    p_window INTEGER DEFAULT 60
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    current_window BIGINT;
    current_count INTEGER;
BEGIN
    -- Compute the current fixed window
    current_window := EXTRACT(EPOCH FROM NOW())::BIGINT / p_window;

    -- Atomic upsert: insert or increment counter
    INSERT INTO rate_limits (api_key_hash, window_start, request_count)
    VALUES (p_key_hash, current_window, 1)
    ON CONFLICT (api_key_hash, window_start)
    DO UPDATE SET request_count = rate_limits.request_count + 1
    RETURNING request_count INTO current_count;

    -- Cleanup: delete stale windows (older than previous window)
    DELETE FROM rate_limits WHERE window_start < current_window - 1;

    RETURN current_count <= p_limit;
END;
$$;

-- 3. Verify
DO $$
BEGIN
    RAISE NOTICE 'Migration 003 complete: rate_limits table and check_rate_limit function created.';
END $$;
