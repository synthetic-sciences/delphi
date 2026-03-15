-- ============================================================================
-- Migration 013: Revoke blanket GRANT ALL, apply least-privilege per table
-- ============================================================================
-- setup_supabase.sql line 1089 grants ALL ON ALL TABLES to authenticated.
-- The backend uses service_role for every write, so authenticated only needs
-- SELECT on tables where RLS SELECT policies exist.
--
-- Rate_limits has no RLS (intentional — service_role only). Revoking all
-- access from authenticated ensures it stays backend-only.
-- ============================================================================

-- ============================================================================
-- STEP 1: Revoke the blanket grant
-- ============================================================================

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;

-- ============================================================================
-- STEP 2: Grant SELECT-only where authenticated has RLS SELECT policies
-- ============================================================================

-- Core tables (repos, papers, datasets) — read via collection membership
GRANT SELECT ON repositories          TO authenticated;
GRANT SELECT ON repository_files      TO authenticated;
GRANT SELECT ON code_chunks           TO authenticated;
GRANT SELECT ON chunk_embeddings      TO authenticated;
GRANT SELECT ON symbols               TO authenticated;

GRANT SELECT ON papers                TO authenticated;
GRANT SELECT ON paper_chunks          TO authenticated;
GRANT SELECT ON paper_chunk_embeddings TO authenticated;
GRANT SELECT ON citations             TO authenticated;
GRANT SELECT ON equations             TO authenticated;
GRANT SELECT ON paper_code_snippets   TO authenticated;

GRANT SELECT ON datasets              TO authenticated;
GRANT SELECT ON dataset_chunks        TO authenticated;
GRANT SELECT ON dataset_chunk_embeddings TO authenticated;

-- Junction tables — users manage their own collection entries
-- RLS: auth.uid() = user_id (FOR ALL)
GRANT SELECT, INSERT, UPDATE, DELETE ON user_repositories TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_papers       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_datasets     TO authenticated;

-- API keys — users manage their own keys
-- RLS: auth.uid() = user_id (per-operation policies)
GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys TO authenticated;

-- Token tables — users manage their own tokens
-- RLS: auth.uid() = user_id (per-operation policies)
GRANT SELECT, INSERT, UPDATE, DELETE ON github_tokens     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON huggingface_tokens TO authenticated;

-- Cost tracking — users can read own costs; backend inserts via service_role
-- RLS: SELECT + INSERT for auth.uid() = user_id
GRANT SELECT ON gemini_costs TO authenticated;

-- Activity log — users can read own activity; backend inserts via service_role
-- RLS: auth.uid() = user_id (FOR ALL)
GRANT SELECT ON activity_log TO authenticated;

-- Indexing jobs — users can read own jobs; backend manages lifecycle
-- RLS: user_id = auth.uid() (FOR ALL)
GRANT SELECT ON indexing_jobs TO authenticated;

-- Security audit log — users can read own entries; backend inserts
-- RLS: SELECT for auth.uid() = user_id
GRANT SELECT ON security_audit_log TO authenticated;

-- rate_limits: NO grant — backend-only via service_role (no RLS, no user access)

-- ============================================================================
-- STEP 3: Ensure service_role still has full access
-- ============================================================================

GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
