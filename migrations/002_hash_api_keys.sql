-- Migration 002: Hash API keys with SHA-256
--
-- Previously, api_keys.api_key stored the raw plaintext key.
-- This migration:
--   1. Enables pgcrypto (required for digest())
--   2. Adds the new key_hash column
--   3. Populates key_hash from existing plaintext keys
--   4. Drops the old api_key column
--   5. Re-creates the unique index on key_hash
--
-- IMPORTANT: After running this migration, plaintext keys are permanently
-- deleted from the database. Ensure all clients are updated to send keys
-- that will be hashed on the server side before validation.
--
-- Run with: psql $DATABASE_URL -f migrations/002_hash_api_keys.sql

-- 1. Ensure pgcrypto extension is available (Supabase has it by default)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2. Add the new column (if it doesn't already exist)
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS key_hash TEXT;

-- 3. Populate key_hash from existing plaintext keys
UPDATE api_keys
SET key_hash = encode(digest(api_key, 'sha256'), 'hex')
WHERE api_key IS NOT NULL AND key_hash IS NULL;

-- 4. Make key_hash NOT NULL and UNIQUE
ALTER TABLE api_keys ALTER COLUMN key_hash SET NOT NULL;

-- Drop the old index if it exists
DROP INDEX IF EXISTS idx_api_keys_key;

-- Create new index on key_hash
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

-- 5. Drop the old plaintext column
ALTER TABLE api_keys DROP COLUMN IF EXISTS api_key;

-- Verify
DO $$
BEGIN
    RAISE NOTICE 'Migration 002 complete: API keys are now stored as SHA-256 hashes.';
    RAISE NOTICE 'The plaintext api_key column has been removed.';
END $$;
