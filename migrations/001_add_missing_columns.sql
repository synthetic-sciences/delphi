-- =============================================================================
-- Migration 001: Add missing columns to match SQLAlchemy models
-- =============================================================================
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- Safe to run multiple times (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
-- =============================================================================

-- ─── repositories ────────────────────────────────────────────────────────────
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS total_tokens INTEGER DEFAULT 0;
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS local_path TEXT;
ALTER TABLE repositories ADD COLUMN IF NOT EXISTS repo_metadata JSONB;

-- ─── repository_files ────────────────────────────────────────────────────────
ALTER TABLE repository_files ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0;
ALTER TABLE repository_files ADD COLUMN IF NOT EXISTS size_bytes INTEGER DEFAULT 0;
ALTER TABLE repository_files ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE repository_files ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- ─── code_chunks ─────────────────────────────────────────────────────────────
ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS token_count INTEGER;
ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS symbol_names TEXT;
ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- ─── symbols ─────────────────────────────────────────────────────────────────
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS parent_symbol_id UUID REFERENCES symbols(symbol_id) ON DELETE SET NULL;
ALTER TABLE symbols ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);

-- ─── Verify ──────────────────────────────────────────────────────────────────
-- Quick sanity check that columns were added:
SELECT 'repositories' as tbl, column_name 
FROM information_schema.columns 
WHERE table_name = 'repositories' AND column_name IN ('total_tokens', 'local_path', 'repo_metadata')

UNION ALL

SELECT 'repository_files', column_name 
FROM information_schema.columns 
WHERE table_name = 'repository_files' AND column_name IN ('token_count', 'size_bytes')

UNION ALL

SELECT 'code_chunks', column_name 
FROM information_schema.columns 
WHERE table_name = 'code_chunks' AND column_name IN ('token_count', 'symbol_names')

ORDER BY tbl, column_name;
