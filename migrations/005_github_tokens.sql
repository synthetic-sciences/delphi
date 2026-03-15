-- ============================================================================
-- Migration 005: GitHub Personal Access Token storage
-- ============================================================================
-- Stores encrypted GitHub PATs for private repo cloning.
-- One token per user. Token value is Fernet-encrypted at the application layer.
-- ============================================================================

CREATE TABLE IF NOT EXISTS github_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
    encrypted_token TEXT NOT NULL,
    token_label TEXT,
    github_username TEXT,
    scopes TEXT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_tokens_user ON github_tokens(user_id);

ALTER TABLE github_tokens ENABLE ROW LEVEL SECURITY;

-- Users can only manage their own token
CREATE POLICY "github_tokens_select" ON github_tokens FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "github_tokens_insert" ON github_tokens FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "github_tokens_update" ON github_tokens FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "github_tokens_delete" ON github_tokens FOR DELETE USING (user_id = auth.uid());
-- Service role for backend operations
CREATE POLICY "github_tokens_service" ON github_tokens FOR ALL TO service_role USING (true);
