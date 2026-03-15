-- =============================================================================
-- SYNSC CONTEXT - Complete Supabase Setup Script
-- =============================================================================
--
-- This script sets up a new Supabase instance with all tables, indexes, 
-- policies, and functions needed for the unified code + paper context service.
--
-- Run this ONCE in your Supabase SQL Editor (Dashboard → SQL Editor → New Query)
--
-- Features:
-- - pgvector for semantic search (768-dim embeddings)
-- - Code repositories with smart deduplication (public repos shared globally)
-- - Research papers with global deduplication by PDF hash
-- - Row Level Security for multi-tenant data isolation
-- - Job queue for async indexing with progress tracking
-- - API key authentication system
--
-- =============================================================================

-- ============================================================================
-- PART 1: EXTENSIONS
-- ============================================================================

-- Enable pgvector for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgcrypto for secure random generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ============================================================================
-- PART 2: API KEYS (Authentication)
-- ============================================================================
-- API keys for CLI and MCP server authentication

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,       -- SHA-256 hex digest of the raw API key
    key_preview TEXT,                    -- First 12 chars for display (synsc_xxxx)
    name TEXT DEFAULT 'Default',
    is_revoked BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY "api_keys_user_select" ON api_keys FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "api_keys_user_insert" ON api_keys FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "api_keys_user_update" ON api_keys FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "api_keys_user_delete" ON api_keys FOR DELETE USING (auth.uid() = user_id);
CREATE POLICY "api_keys_service" ON api_keys FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 3: REPOSITORIES (Code Context - Global Deduplication)
-- ============================================================================
-- Public repos are stored once globally and shared by all users
-- Private repos are per-user isolated

CREATE TABLE IF NOT EXISTS repositories (
    repo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Repository identity
    url TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    branch TEXT DEFAULT 'main',
    commit_sha TEXT,
    description TEXT,
    
    -- Visibility (TRUE = shared globally, FALSE = private to indexed_by user)
    is_public BOOLEAN DEFAULT TRUE,
    
    -- Who first indexed this repo
    indexed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    
    -- Statistics
    files_count INTEGER DEFAULT 0,
    chunks_count INTEGER DEFAULT 0,
    symbols_count INTEGER DEFAULT 0,
    total_lines INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    languages JSONB DEFAULT '{}',
    
    -- Optional metadata
    local_path TEXT,
    repo_metadata JSONB,
    
    -- Timestamps
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Unique constraint for deduplication
    UNIQUE(url, branch)
);

CREATE INDEX IF NOT EXISTS idx_repos_public ON repositories(is_public);
CREATE INDEX IF NOT EXISTS idx_repos_owner_name ON repositories(owner, name);
CREATE INDEX IF NOT EXISTS idx_repos_indexed_by ON repositories(indexed_by);

ALTER TABLE repositories ENABLE ROW LEVEL SECURITY;

-- Public repos: everyone can read; Private repos: only indexer can access
CREATE POLICY "repos_read" ON repositories FOR SELECT USING (
    is_public = TRUE OR indexed_by = auth.uid()
);
CREATE POLICY "repos_insert" ON repositories FOR INSERT WITH CHECK (
    indexed_by = auth.uid()
);
CREATE POLICY "repos_update" ON repositories FOR UPDATE USING (
    indexed_by = auth.uid()
);
CREATE POLICY "repos_delete" ON repositories FOR DELETE USING (
    indexed_by = auth.uid()
);
CREATE POLICY "repos_service" ON repositories FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 4: USER REPOSITORIES (Junction Table)
-- ============================================================================
-- Links users to repositories (bookmarking public repos, owning private repos)

CREATE TABLE IF NOT EXISTS user_repositories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    
    nickname TEXT,
    is_favorite BOOLEAN DEFAULT FALSE,
    
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ,
    search_count INTEGER DEFAULT 0,
    
    UNIQUE(user_id, repo_id)
);

CREATE INDEX IF NOT EXISTS idx_user_repos_user ON user_repositories(user_id);
CREATE INDEX IF NOT EXISTS idx_user_repos_repo ON user_repositories(repo_id);

ALTER TABLE user_repositories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_repos_policy" ON user_repositories FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "user_repos_service" ON user_repositories FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 5: REPOSITORY FILES
-- ============================================================================

CREATE TABLE IF NOT EXISTS repository_files (
    file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    language TEXT,
    line_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    size_bytes INTEGER DEFAULT 0,
    content_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(repo_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_files_repo ON repository_files(repo_id);
CREATE INDEX IF NOT EXISTS idx_files_language ON repository_files(language);

ALTER TABLE repository_files ENABLE ROW LEVEL SECURITY;

CREATE POLICY "files_read" ON repository_files FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r 
        WHERE r.repo_id = repository_files.repo_id 
        AND (r.is_public = TRUE OR r.indexed_by = auth.uid())
    )
);
CREATE POLICY "files_service" ON repository_files FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 6: CODE CHUNKS
-- ============================================================================

CREATE TABLE IF NOT EXISTS code_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES repository_files(file_id) ON DELETE CASCADE,
    
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    chunk_type TEXT DEFAULT 'code',
    language TEXT,
    token_count INTEGER,
    symbol_names TEXT,  -- JSON array of symbol names
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_repo ON code_chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON code_chunks(file_id);

ALTER TABLE code_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chunks_read" ON code_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r 
        WHERE r.repo_id = code_chunks.repo_id 
        AND (r.is_public = TRUE OR r.indexed_by = auth.uid())
    )
);
CREATE POLICY "chunks_service" ON code_chunks FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 7: CODE CHUNK EMBEDDINGS (pgvector)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES code_chunks(chunk_id) ON DELETE CASCADE UNIQUE,
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_repo ON chunk_embeddings(repo_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON chunk_embeddings(chunk_id);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON chunk_embeddings 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE chunk_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "embeddings_read" ON chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r 
        WHERE r.repo_id = chunk_embeddings.repo_id 
        AND (r.is_public = TRUE OR r.indexed_by = auth.uid())
    )
);
CREATE POLICY "embeddings_service" ON chunk_embeddings FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 8: SYMBOLS (Functions, Classes, Methods)
-- ============================================================================

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES repository_files(file_id) ON DELETE CASCADE,
    
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,  -- function, class, method, variable, etc.
    signature TEXT,
    docstring TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    language TEXT,
    parameters JSONB DEFAULT '[]',
    return_type TEXT,
    decorators JSONB DEFAULT '[]',
    is_async BOOLEAN DEFAULT FALSE,
    is_exported BOOLEAN DEFAULT FALSE,
    parent_symbol_id UUID REFERENCES symbols(symbol_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_symbols_repo ON symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);

ALTER TABLE symbols ENABLE ROW LEVEL SECURITY;

CREATE POLICY "symbols_read" ON symbols FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM repositories r 
        WHERE r.repo_id = symbols.repo_id 
        AND (r.is_public = TRUE OR r.indexed_by = auth.uid())
    )
);
CREATE POLICY "symbols_service" ON symbols FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 9: PAPERS (Research Paper Context)
-- ============================================================================
-- Papers are globally deduplicated by pdf_hash

CREATE TABLE IF NOT EXISTS papers (
    paper_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Paper identity
    arxiv_id TEXT UNIQUE,
    title TEXT NOT NULL,
    authors JSONB DEFAULT '[]',
    abstract TEXT,
    published_date TEXT,
    pdf_url TEXT,
    pdf_hash TEXT NOT NULL UNIQUE,
    
    -- Visibility
    is_public BOOLEAN DEFAULT FALSE,
    indexed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    
    -- Statistics
    page_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    citation_count INTEGER DEFAULT 0,
    
    -- Timestamps
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Full report (JSON)
    report JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_hash ON papers(pdf_hash);
CREATE INDEX IF NOT EXISTS idx_papers_public ON papers(is_public);
CREATE INDEX IF NOT EXISTS idx_papers_indexed_by ON papers(indexed_by);

ALTER TABLE papers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "papers_read" ON papers FOR SELECT USING (
    is_public = TRUE OR indexed_by = auth.uid()
);
CREATE POLICY "papers_insert" ON papers FOR INSERT WITH CHECK (
    indexed_by = auth.uid()
);
CREATE POLICY "papers_update" ON papers FOR UPDATE USING (
    indexed_by = auth.uid()
);
CREATE POLICY "papers_delete" ON papers FOR DELETE USING (
    indexed_by = auth.uid()
);
CREATE POLICY "papers_service" ON papers FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 10: USER PAPERS (Junction Table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_papers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    
    notes TEXT,
    is_favorite BOOLEAN DEFAULT FALSE,
    
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ,
    search_count INTEGER DEFAULT 0,
    
    UNIQUE(user_id, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_user_papers_user ON user_papers(user_id);
CREATE INDEX IF NOT EXISTS idx_user_papers_paper ON user_papers(paper_id);

ALTER TABLE user_papers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_papers_policy" ON user_papers FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "user_papers_service" ON user_papers FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 11: PAPER CHUNKS
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    
    chunk_index INTEGER NOT NULL,
    section_title TEXT,
    content TEXT NOT NULL,
    chunk_type TEXT DEFAULT 'paragraph',  -- paragraph, abstract, conclusion, etc.
    page_number INTEGER,
    token_count INTEGER,
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(paper_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper ON paper_chunks(paper_id);

ALTER TABLE paper_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "paper_chunks_read" ON paper_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p 
        WHERE p.paper_id = paper_chunks.paper_id 
        AND (p.is_public = TRUE OR p.indexed_by = auth.uid())
    )
);
CREATE POLICY "paper_chunks_service" ON paper_chunks FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 12: PAPER CHUNK EMBEDDINGS (pgvector)
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_chunk_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES paper_chunks(chunk_id) ON DELETE CASCADE UNIQUE,
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_embeddings_paper ON paper_chunk_embeddings(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_embeddings_chunk ON paper_chunk_embeddings(chunk_id);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_paper_embeddings_vector ON paper_chunk_embeddings 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE paper_chunk_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "paper_embeddings_read" ON paper_chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p 
        WHERE p.paper_id = paper_chunk_embeddings.paper_id 
        AND (p.is_public = TRUE OR p.indexed_by = auth.uid())
    )
);
CREATE POLICY "paper_embeddings_service" ON paper_chunk_embeddings FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 13: CITATIONS (Extracted from Papers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS citations (
    citation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    cited_paper_id UUID REFERENCES papers(paper_id) ON DELETE SET NULL,
    
    citation_text TEXT NOT NULL,
    citation_context TEXT,
    page_number INTEGER,
    citation_number INTEGER,
    external_reference JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_citations_paper ON citations(paper_id);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_paper_id);

ALTER TABLE citations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "citations_read" ON citations FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p 
        WHERE p.paper_id = citations.paper_id 
        AND (p.is_public = TRUE OR p.indexed_by = auth.uid())
    )
);
CREATE POLICY "citations_service" ON citations FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 14: EQUATIONS (LaTeX Extracted from Papers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS equations (
    equation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    
    equation_text TEXT NOT NULL,  -- LaTeX
    equation_number TEXT,
    section_title TEXT,
    page_number INTEGER,
    context TEXT,
    equation_type TEXT DEFAULT 'display',  -- inline, display, numbered
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_equations_paper ON equations(paper_id);

ALTER TABLE equations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "equations_read" ON equations FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p 
        WHERE p.paper_id = equations.paper_id 
        AND (p.is_public = TRUE OR p.indexed_by = auth.uid())
    )
);
CREATE POLICY "equations_service" ON equations FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 15: CODE SNIPPETS (From Papers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_code_snippets (
    snippet_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    
    code_text TEXT NOT NULL,
    language TEXT,
    page_number INTEGER,
    section_title TEXT,
    listing_number TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_snippets_paper ON paper_code_snippets(paper_id);

ALTER TABLE paper_code_snippets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "paper_snippets_read" ON paper_code_snippets FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM papers p 
        WHERE p.paper_id = paper_code_snippets.paper_id 
        AND (p.is_public = TRUE OR p.indexed_by = auth.uid())
    )
);
CREATE POLICY "paper_snippets_service" ON paper_code_snippets FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 16: INDEXING JOBS (Background Job Queue)
-- ============================================================================

CREATE TABLE IF NOT EXISTS indexing_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Job owner
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Job type: 'repository' or 'paper'
    job_type TEXT DEFAULT 'repository',
    
    -- For repositories
    repo_url TEXT,
    branch TEXT DEFAULT 'main',
    
    -- For papers
    paper_source TEXT,  -- arXiv URL/ID or file path
    
    -- Status: pending, processing, completed, failed, cancelled
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 0,
    
    -- Progress tracking
    progress FLOAT DEFAULT 0.0,
    current_stage TEXT,
    current_message TEXT,
    
    -- Stats
    files_total INTEGER DEFAULT 0,
    files_processed INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    symbols_extracted INTEGER DEFAULT 0,
    
    -- Timing
    estimated_seconds INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Results
    result_repo_id UUID REFERENCES repositories(repo_id) ON DELETE SET NULL,
    result_paper_id UUID REFERENCES papers(paper_id) ON DELETE SET NULL,
    error_message TEXT,
    
    -- Worker tracking
    worker_id TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON indexing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON indexing_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON indexing_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_priority_status ON indexing_jobs(priority DESC, status);

ALTER TABLE indexing_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "jobs_user" ON indexing_jobs FOR ALL USING (user_id = auth.uid());
CREATE POLICY "jobs_service" ON indexing_jobs FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 17: ACTIVITY LOG (Per-User)
-- ============================================================================

CREATE TABLE IF NOT EXISTS activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    resource_type TEXT,  -- 'repository', 'paper', 'search'
    resource_id UUID,
    query TEXT,
    results_count INTEGER,
    duration_ms INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);

ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "activity_policy" ON activity_log FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "activity_service" ON activity_log FOR ALL TO service_role USING (true);


-- ============================================================================
-- PART 18: GEMINI API COST TRACKING (Per-User)
-- ============================================================================

CREATE TABLE IF NOT EXISTS gemini_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    resource_id UUID,
    token_count INTEGER NOT NULL,
    cost_usd NUMERIC(12, 8) NOT NULL,
    model TEXT NOT NULL DEFAULT 'gemini-embedding-001',
    batch_count INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gemini_costs_user ON gemini_costs(user_id);
CREATE INDEX IF NOT EXISTS idx_gemini_costs_created ON gemini_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_gemini_costs_operation ON gemini_costs(operation);

ALTER TABLE gemini_costs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "gemini_costs_select" ON gemini_costs
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "gemini_costs_insert" ON gemini_costs
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "gemini_costs_service" ON gemini_costs
    FOR ALL TO service_role USING (true);

-- Server-side aggregation for cost summary
CREATE OR REPLACE FUNCTION get_gemini_cost_summary(
    p_user_id UUID,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    total_tokens BIGINT,
    total_cost_usd NUMERIC(12, 8),
    total_requests BIGINT,
    by_operation JSONB
)
LANGUAGE sql STABLE
AS $$
    WITH filtered AS (
        SELECT * FROM gemini_costs
        WHERE user_id = p_user_id
          AND (p_since IS NULL OR created_at >= p_since)
    ),
    totals AS (
        SELECT
            COALESCE(SUM(token_count), 0)::BIGINT AS total_tokens,
            COALESCE(SUM(cost_usd), 0)::NUMERIC(12, 8) AS total_cost_usd,
            COUNT(*)::BIGINT AS total_requests
        FROM filtered
    ),
    ops AS (
        SELECT COALESCE(
            jsonb_object_agg(operation, jsonb_build_object(
                'tokens', tokens,
                'cost_usd', cost,
                'count', cnt
            )),
            '{}'::jsonb
        ) AS by_operation
        FROM (
            SELECT
                operation,
                SUM(token_count) AS tokens,
                SUM(cost_usd) AS cost,
                COUNT(*) AS cnt
            FROM filtered
            GROUP BY operation
        ) sub
    )
    SELECT t.total_tokens, t.total_cost_usd, t.total_requests, o.by_operation
    FROM totals t, ops o;
$$;

GRANT EXECUTE ON FUNCTION get_gemini_cost_summary TO authenticated;
GRANT EXECUTE ON FUNCTION get_gemini_cost_summary TO service_role;


-- ============================================================================
-- PART 19: RATE LIMITS (Database-backed rate limiting)
-- ============================================================================
-- Fixed-window rate limiting using atomic UPSERT.
-- Shared across all API workers and instances.

CREATE TABLE IF NOT EXISTS rate_limits (
    api_key_hash TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (api_key_hash, window_start)
);

-- Atomic check-and-increment: returns TRUE if under limit, FALSE if exceeded.
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
    current_window := EXTRACT(EPOCH FROM NOW())::BIGINT / p_window;

    INSERT INTO rate_limits (api_key_hash, window_start, request_count)
    VALUES (p_key_hash, current_window, 1)
    ON CONFLICT (api_key_hash, window_start)
    DO UPDATE SET request_count = rate_limits.request_count + 1
    RETURNING request_count INTO current_count;

    DELETE FROM rate_limits WHERE window_start < current_window - 1;

    RETURN current_count <= p_limit;
END;
$$;


-- ============================================================================
-- PART 20: HELPER FUNCTIONS
-- ============================================================================

-- Create API key for a user (stores SHA-256 hash, returns plaintext once)
CREATE OR REPLACE FUNCTION create_api_key(p_user_id UUID, p_name TEXT DEFAULT 'Default')
RETURNS TEXT AS $$
DECLARE
    new_key TEXT;
    key_prev TEXT;
    hashed TEXT;
BEGIN
    new_key := 'synsc_' || replace(replace(replace(
        encode(gen_random_bytes(32), 'base64'), '+', ''), '/', ''), '=', '');
    key_prev := substring(new_key from 1 for 12);
    hashed  := encode(digest(new_key, 'sha256'), 'hex');
    INSERT INTO api_keys (user_id, key_hash, key_preview, name)
    VALUES (p_user_id, hashed, key_prev, p_name);
    RETURN new_key;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Check if repo already indexed (for deduplication)
CREATE OR REPLACE FUNCTION get_existing_repo(p_url TEXT, p_branch TEXT)
RETURNS UUID AS $$
    SELECT repo_id FROM repositories WHERE url = p_url AND branch = p_branch;
$$ LANGUAGE sql SECURITY DEFINER;


-- Check if paper already indexed (for deduplication)
CREATE OR REPLACE FUNCTION get_existing_paper(p_pdf_hash TEXT)
RETURNS UUID AS $$
    SELECT paper_id FROM papers WHERE pdf_hash = p_pdf_hash;
$$ LANGUAGE sql SECURITY DEFINER;


-- Add repo to user's collection
CREATE OR REPLACE FUNCTION add_repo_to_user(p_user_id UUID, p_repo_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO user_repositories (user_id, repo_id)
    VALUES (p_user_id, p_repo_id)
    ON CONFLICT (user_id, repo_id) DO UPDATE SET last_searched_at = NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Add paper to user's collection
CREATE OR REPLACE FUNCTION add_paper_to_user(p_user_id UUID, p_paper_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO user_papers (user_id, paper_id)
    VALUES (p_user_id, p_paper_id)
    ON CONFLICT (user_id, paper_id) DO UPDATE SET last_searched_at = NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Search code chunks (respects visibility rules)
CREATE OR REPLACE FUNCTION search_code(
    query_embedding vector(768),
    p_user_id UUID,
    p_repo_ids UUID[] DEFAULT NULL,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id UUID,
    repo_id UUID,
    content TEXT,
    file_path TEXT,
    repo_name TEXT,
    start_line INTEGER,
    end_line INTEGER,
    language TEXT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        cc.chunk_id,
        cc.repo_id,
        cc.content,
        rf.file_path,
        r.owner || '/' || r.name,
        cc.start_line,
        cc.end_line,
        cc.language,
        1 - (ce.embedding <=> query_embedding)
    FROM chunk_embeddings ce
    JOIN code_chunks cc ON ce.chunk_id = cc.chunk_id
    JOIN repository_files rf ON cc.file_id = rf.file_id
    JOIN repositories r ON cc.repo_id = r.repo_id
    WHERE (r.is_public = TRUE OR r.indexed_by = p_user_id)
    AND (p_repo_ids IS NULL OR ce.repo_id = ANY(p_repo_ids))
    AND EXISTS (
        SELECT 1 FROM user_repositories ur 
        WHERE ur.user_id = p_user_id AND ur.repo_id = r.repo_id
    )
    ORDER BY ce.embedding <=> query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Search paper chunks (respects visibility rules)
CREATE OR REPLACE FUNCTION search_papers(
    query_embedding vector(768),
    p_user_id UUID,
    p_paper_ids UUID[] DEFAULT NULL,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id UUID,
    paper_id UUID,
    content TEXT,
    section_title TEXT,
    paper_title TEXT,
    page_number INTEGER,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        pc.chunk_id,
        pc.paper_id,
        pc.content,
        pc.section_title,
        p.title,
        pc.page_number,
        1 - (pce.embedding <=> query_embedding)
    FROM paper_chunk_embeddings pce
    JOIN paper_chunks pc ON pce.chunk_id = pc.chunk_id
    JOIN papers p ON pc.paper_id = p.paper_id
    WHERE (p.is_public = TRUE OR p.indexed_by = p_user_id)
    AND (p_paper_ids IS NULL OR pce.paper_id = ANY(p_paper_ids))
    AND EXISTS (
        SELECT 1 FROM user_papers up 
        WHERE up.user_id = p_user_id AND up.paper_id = p.paper_id
    )
    ORDER BY pce.embedding <=> query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Match paper chunks (simpler RPC for REST API usage)
CREATE OR REPLACE FUNCTION match_paper_chunks(
    query_embedding vector(768),
    match_user_id uuid,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    chunk_id uuid,
    paper_id uuid,
    chunk_index int,
    content text,
    section_title text,
    chunk_type text,
    page_number int,
    paper_title text,
    paper_authors jsonb,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        pc.chunk_id,
        pc.paper_id,
        pc.chunk_index,
        pc.content,
        pc.section_title,
        pc.chunk_type,
        pc.page_number,
        p.title AS paper_title,
        p.authors::jsonb AS paper_authors,
        1 - (pce.embedding <=> query_embedding) AS similarity
    FROM paper_chunk_embeddings pce
    INNER JOIN paper_chunks pc ON pce.chunk_id = pc.chunk_id
    INNER JOIN papers p ON pc.paper_id = p.paper_id
    INNER JOIN user_papers up ON p.paper_id = up.paper_id
    WHERE up.user_id = match_user_id
    ORDER BY pce.embedding <=> query_embedding
    LIMIT match_count;
$$;


-- List user's repositories
CREATE OR REPLACE FUNCTION list_user_repos(p_user_id UUID)
RETURNS TABLE (
    repo_id UUID,
    url TEXT,
    owner TEXT,
    name TEXT,
    branch TEXT,
    is_public BOOLEAN,
    is_owner BOOLEAN,
    files_count INTEGER,
    chunks_count INTEGER,
    added_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        r.repo_id,
        r.url,
        r.owner,
        r.name,
        r.branch,
        r.is_public,
        r.indexed_by = p_user_id AS is_owner,
        r.files_count,
        r.chunks_count,
        ur.added_at
    FROM user_repositories ur
    JOIN repositories r ON ur.repo_id = r.repo_id
    WHERE ur.user_id = p_user_id
    ORDER BY ur.added_at DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- List user's papers
CREATE OR REPLACE FUNCTION list_user_papers(p_user_id UUID)
RETURNS TABLE (
    paper_id UUID,
    arxiv_id TEXT,
    title TEXT,
    authors JSONB,
    is_public BOOLEAN,
    is_owner BOOLEAN,
    page_count INTEGER,
    chunk_count INTEGER,
    added_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.paper_id,
        p.arxiv_id,
        p.title,
        p.authors,
        p.is_public,
        p.indexed_by = p_user_id AS is_owner,
        p.page_count,
        p.chunk_count,
        up.added_at
    FROM user_papers up
    JOIN papers p ON up.paper_id = p.paper_id
    WHERE up.user_id = p_user_id
    ORDER BY up.added_at DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Claim next pending job (for workers)
CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id TEXT)
RETURNS UUID AS $$
DECLARE
    claimed_job_id UUID;
BEGIN
    UPDATE indexing_jobs
    SET 
        status = 'processing',
        worker_id = p_worker_id,
        started_at = NOW(),
        updated_at = NOW()
    WHERE job_id = (
        SELECT job_id 
        FROM indexing_jobs 
        WHERE status = 'pending'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING job_id INTO claimed_job_id;
    
    RETURN claimed_job_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- Update job progress
CREATE OR REPLACE FUNCTION update_job_progress(
    p_job_id UUID,
    p_progress FLOAT,
    p_stage TEXT,
    p_message TEXT
)
RETURNS void AS $$
BEGIN
    UPDATE indexing_jobs
    SET 
        progress = p_progress,
        current_stage = p_stage,
        current_message = p_message,
        updated_at = NOW()
    WHERE job_id = p_job_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ============================================================================
-- PART 21: GRANT PERMISSIONS
-- ============================================================================

-- Grant function execute permissions
GRANT EXECUTE ON FUNCTION create_api_key TO authenticated;
GRANT EXECUTE ON FUNCTION get_existing_repo TO authenticated;
GRANT EXECUTE ON FUNCTION get_existing_paper TO authenticated;
GRANT EXECUTE ON FUNCTION add_repo_to_user TO authenticated;
GRANT EXECUTE ON FUNCTION add_paper_to_user TO authenticated;
GRANT EXECUTE ON FUNCTION search_code TO authenticated;
GRANT EXECUTE ON FUNCTION search_papers TO authenticated;
GRANT EXECUTE ON FUNCTION match_paper_chunks TO authenticated;
GRANT EXECUTE ON FUNCTION list_user_repos TO authenticated;
GRANT EXECUTE ON FUNCTION list_user_papers TO authenticated;

-- Service role gets all function access
GRANT EXECUTE ON FUNCTION claim_next_job TO service_role;
GRANT EXECUTE ON FUNCTION update_job_progress TO service_role;
GRANT EXECUTE ON FUNCTION check_rate_limit TO service_role;

-- Grant table access
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;


-- ============================================================================
-- LOCAL DEVELOPMENT DATA
-- ============================================================================

-- Create a default dev user (only works in local Supabase)
-- In production, users are created via Supabase Auth (GitHub OAuth)
DO $$
BEGIN
    -- Insert into auth.users if it doesn't exist (local dev only)
    IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = '00000000-0000-0000-0000-000000000001') THEN
        INSERT INTO auth.users (
            id,
            instance_id,
            email,
            encrypted_password,
            email_confirmed_at,
            raw_app_meta_data,
            raw_user_meta_data,
            created_at,
            updated_at,
            aud,
            role
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000000',
            'dev@localhost',
            '',
            NOW(),
            '{"provider":"email","providers":["email"]}',
            '{"name":"Dev User"}',
            NOW(),
            NOW(),
            'authenticated',
            'authenticated'
        );
    END IF;
END $$;

-- Create a dev API key for local testing (stored as SHA-256 hash)
-- The raw key is: synsc_dev_key_for_local_testing_only_do_not_use_in_production
INSERT INTO api_keys (user_id, key_hash, key_preview, name)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    encode(digest('synsc_dev_key_for_local_testing_only_do_not_use_in_production', 'sha256'), 'hex'),
    'synsc_dev_ke',
    'Local Development Key'
)
ON CONFLICT (key_hash) DO NOTHING;


-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- List all created tables
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN (
    'api_keys',
    'repositories', 'user_repositories', 'repository_files', 'code_chunks', 'chunk_embeddings', 'symbols',
    'papers', 'user_papers', 'paper_chunks', 'paper_chunk_embeddings', 'citations', 'equations', 'paper_code_snippets',
    'indexing_jobs', 'activity_log'
)
ORDER BY table_name;


-- ============================================================================
-- SETUP COMPLETE!
-- ============================================================================
--
-- Tables created:
--   Code Context:
--   - api_keys: Authentication tokens
--   - repositories: GitHub repositories (deduplicated)
--   - user_repositories: User-repo associations
--   - repository_files: Files in repos
--   - code_chunks: Code chunks for search
--   - chunk_embeddings: Vector embeddings (pgvector)
--   - symbols: Functions, classes, methods
--
--   Paper Context:
--   - papers: Research papers (deduplicated by pdf_hash)
--   - user_papers: User-paper associations
--   - paper_chunks: Paper text chunks
--   - paper_chunk_embeddings: Vector embeddings (pgvector)
--   - citations: Extracted citations
--   - equations: LaTeX equations
--   - paper_code_snippets: Code from papers
--
--   Infrastructure:
--   - indexing_jobs: Background job queue
--   - activity_log: User activity tracking
--   - gemini_costs: Per-user Gemini API cost tracking
--
-- Next steps:
--   1. Copy SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from Supabase dashboard
--   2. Set environment variables in your .env file
--   3. Configure GitHub OAuth in Supabase Auth settings
--   4. Deploy your backend and connect!
--
-- ============================================================================
