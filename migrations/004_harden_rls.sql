-- ============================================================================
-- Migration 004: Harden RLS policies + Security Audit Log
-- ============================================================================
-- Tightens READ policies to require collection membership (via junction tables)
-- instead of allowing any authenticated user to read all public resources.
-- Also adds a security_audit_log table for tracking sensitive operations.
-- ============================================================================

-- ============================================================================
-- PART 1: HARDEN REPOSITORY RLS POLICIES
-- ============================================================================

-- Repositories: owner OR collection member
DROP POLICY IF EXISTS "repos_read" ON repositories;
CREATE POLICY "repos_read" ON repositories FOR SELECT USING (
    indexed_by = auth.uid()
    OR EXISTS (
        SELECT 1 FROM user_repositories ur
        WHERE ur.user_id = auth.uid() AND ur.repo_id = repositories.repo_id
    )
);

-- Repository files: inherit from repositories via collection membership
DROP POLICY IF EXISTS "files_read" ON repository_files;
CREATE POLICY "files_read" ON repository_files FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r
        WHERE r.repo_id = repository_files.repo_id
        AND (
            r.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_repositories ur
                WHERE ur.user_id = auth.uid() AND ur.repo_id = r.repo_id
            )
        )
    )
);

-- Code chunks: inherit from repositories via collection membership
DROP POLICY IF EXISTS "chunks_read" ON code_chunks;
CREATE POLICY "chunks_read" ON code_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r
        WHERE r.repo_id = code_chunks.repo_id
        AND (
            r.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_repositories ur
                WHERE ur.user_id = auth.uid() AND ur.repo_id = r.repo_id
            )
        )
    )
);

-- Chunk embeddings: inherit from repositories via collection membership
DROP POLICY IF EXISTS "embeddings_read" ON chunk_embeddings;
CREATE POLICY "embeddings_read" ON chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r
        WHERE r.repo_id = chunk_embeddings.repo_id
        AND (
            r.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_repositories ur
                WHERE ur.user_id = auth.uid() AND ur.repo_id = r.repo_id
            )
        )
    )
);

-- Symbols: inherit from repositories via collection membership
DROP POLICY IF EXISTS "symbols_read" ON symbols;
CREATE POLICY "symbols_read" ON symbols FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r
        WHERE r.repo_id = symbols.repo_id
        AND (
            r.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_repositories ur
                WHERE ur.user_id = auth.uid() AND ur.repo_id = r.repo_id
            )
        )
    )
);


-- ============================================================================
-- PART 2: HARDEN PAPER RLS POLICIES
-- ============================================================================

-- Papers: owner OR collection member
DROP POLICY IF EXISTS "papers_read" ON papers;
CREATE POLICY "papers_read" ON papers FOR SELECT USING (
    indexed_by = auth.uid()
    OR EXISTS (
        SELECT 1 FROM user_papers up
        WHERE up.user_id = auth.uid() AND up.paper_id = papers.paper_id
    )
);

-- Paper chunks: inherit from papers via collection membership
DROP POLICY IF EXISTS "paper_chunks_read" ON paper_chunks;
CREATE POLICY "paper_chunks_read" ON paper_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p
        WHERE p.paper_id = paper_chunks.paper_id
        AND (
            p.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_papers up
                WHERE up.user_id = auth.uid() AND up.paper_id = p.paper_id
            )
        )
    )
);

-- Paper chunk embeddings: inherit from papers via collection membership
DROP POLICY IF EXISTS "paper_embeddings_read" ON paper_chunk_embeddings;
CREATE POLICY "paper_embeddings_read" ON paper_chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p
        WHERE p.paper_id = paper_chunk_embeddings.paper_id
        AND (
            p.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_papers up
                WHERE up.user_id = auth.uid() AND up.paper_id = p.paper_id
            )
        )
    )
);

-- Citations: inherit from papers via collection membership
DROP POLICY IF EXISTS "citations_read" ON citations;
CREATE POLICY "citations_read" ON citations FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p
        WHERE p.paper_id = citations.paper_id
        AND (
            p.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_papers up
                WHERE up.user_id = auth.uid() AND up.paper_id = p.paper_id
            )
        )
    )
);

-- Equations: inherit from papers via collection membership
DROP POLICY IF EXISTS "equations_read" ON equations;
CREATE POLICY "equations_read" ON equations FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p
        WHERE p.paper_id = equations.paper_id
        AND (
            p.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_papers up
                WHERE up.user_id = auth.uid() AND up.paper_id = p.paper_id
            )
        )
    )
);

-- Paper code snippets: inherit from papers via collection membership
DROP POLICY IF EXISTS "paper_snippets_read" ON paper_code_snippets;
CREATE POLICY "paper_snippets_read" ON paper_code_snippets FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p
        WHERE p.paper_id = paper_code_snippets.paper_id
        AND (
            p.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_papers up
                WHERE up.user_id = auth.uid() AND up.paper_id = p.paper_id
            )
        )
    )
);


-- ============================================================================
-- PART 3: SECURITY AUDIT LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON security_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON security_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON security_audit_log(created_at);

ALTER TABLE security_audit_log ENABLE ROW LEVEL SECURITY;

-- Users can only read their own audit entries
CREATE POLICY "audit_own" ON security_audit_log FOR SELECT USING (user_id = auth.uid());
-- Service role can insert (backend logs on behalf of users)
CREATE POLICY "audit_service" ON security_audit_log FOR ALL TO service_role USING (true);
