-- ============================================================================
-- Migration 007: HuggingFace Token storage
-- ============================================================================
-- Stores encrypted HuggingFace tokens for dataset indexing.
-- One token per user. Token value is Fernet-encrypted at the application layer.
-- Mirrors the github_tokens pattern from migration 005.
-- ============================================================================

CREATE TABLE IF NOT EXISTS huggingface_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
    encrypted_token TEXT NOT NULL,
    token_label TEXT,
    hf_username TEXT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_huggingface_tokens_user ON huggingface_tokens(user_id);

ALTER TABLE huggingface_tokens ENABLE ROW LEVEL SECURITY;

-- Users can only manage their own token
CREATE POLICY "huggingface_tokens_select" ON huggingface_tokens FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "huggingface_tokens_insert" ON huggingface_tokens FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "huggingface_tokens_update" ON huggingface_tokens FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "huggingface_tokens_delete" ON huggingface_tokens FOR DELETE USING (user_id = auth.uid());
-- Service role for backend operations
CREATE POLICY "huggingface_tokens_service" ON huggingface_tokens FOR ALL TO service_role USING (true);
