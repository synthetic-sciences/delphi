-- Migration 010: Add github_id column to github_tokens table
-- Maps users to external tier management Supabase via GitHub ID

-- ============================================================================
-- Add github_id column
-- ============================================================================

-- Add github_id column (nullable for gradual rollout)
ALTER TABLE github_tokens ADD COLUMN IF NOT EXISTS github_id BIGINT;

-- Index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_github_tokens_github_id ON github_tokens(github_id);

-- Unique constraint (one GitHub account per Supabase user)
-- This prevents a single GitHub account from being linked to multiple users
ALTER TABLE github_tokens ADD CONSTRAINT unique_github_id UNIQUE (github_id);

-- ============================================================================
-- Notes
-- ============================================================================
-- 1. Column is nullable initially - backfill happens post-deployment
-- 2. Run scripts/backfill_github_ids.py to populate github_id for existing users
-- 3. New GitHub token storage will automatically capture github_id going forward
