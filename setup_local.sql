-- =============================================================================
-- DELPHI - Local Setup Script
-- =============================================================================
--
-- This script sets up a local PostgreSQL instance with all tables, indexes,
-- and functions needed for the unified code + paper context service.
--
-- Run this ONCE against your local PostgreSQL database.
--
-- Features:
-- - pgvector for semantic search (768-dim embeddings)
-- - Code repositories with smart deduplication (public repos shared globally)
-- - Research papers with global deduplication by PDF hash
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
-- PART 2: USERS (Local Auth)
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    name TEXT,
    avatar_url TEXT,
    github_id BIGINT UNIQUE,           -- GitHub user ID (stable across username changes)
    github_username TEXT,               -- GitHub login (display only, can change)
    is_admin BOOLEAN DEFAULT FALSE,     -- First user to sign up becomes admin
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id);


-- ============================================================================
-- PART 3: API KEYS (Authentication)
-- ============================================================================
-- API keys for CLI and MCP server authentication

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,       -- SHA-256 hex digest of the raw API key
    key_preview TEXT,                    -- First 12 chars for display (synsc_xxxx)
    name TEXT DEFAULT 'Default',
    is_revoked BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);


-- ============================================================================
-- PART 3b: GITHUB TOKENS (Per-User PATs for Private Repo Access)
-- ============================================================================

CREATE TABLE IF NOT EXISTS github_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE,
    encrypted_token TEXT NOT NULL,   -- Fernet-encrypted or plaintext GitHub PAT
    token_label TEXT,
    github_username TEXT,
    github_id BIGINT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_tokens_user ON github_tokens(user_id);


-- ============================================================================
-- PART 3c: HUGGINGFACE TOKENS (Per-User HF API Tokens)
-- ============================================================================

CREATE TABLE IF NOT EXISTS huggingface_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE,
    encrypted_token TEXT NOT NULL,   -- Fernet-encrypted or plaintext HF token
    token_label TEXT,
    hf_username TEXT,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hf_tokens_user ON huggingface_tokens(user_id);


-- ============================================================================
-- PART 4: REPOSITORIES (Code Context - Global Deduplication)
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
    indexed_by UUID,

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


-- ============================================================================
-- PART 5: USER REPOSITORIES (Junction Table)
-- ============================================================================
-- Links users to repositories (bookmarking public repos, owning private repos)

CREATE TABLE IF NOT EXISTS user_repositories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
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


-- ============================================================================
-- PART 6: REPOSITORY FILES
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


-- ============================================================================
-- PART 7: CODE CHUNKS
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


-- ============================================================================
-- PART 8: CODE CHUNK EMBEDDINGS (pgvector)
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


-- ============================================================================
-- PART 9: SYMBOLS (Functions, Classes, Methods)
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


-- ============================================================================
-- PART 10: PAPERS (Research Paper Context)
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
    indexed_by UUID,

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


-- ============================================================================
-- PART 11: USER PAPERS (Junction Table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_papers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
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


-- ============================================================================
-- PART 12: PAPER CHUNKS
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


-- ============================================================================
-- PART 13: PAPER CHUNK EMBEDDINGS (pgvector)
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


-- ============================================================================
-- PART 14: CITATIONS (Extracted from Papers)
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


-- ============================================================================
-- PART 15: EQUATIONS (LaTeX Extracted from Papers)
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


-- ============================================================================
-- PART 16: CODE SNIPPETS (From Papers)
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


-- ============================================================================
-- PART 16b: DATASETS (HuggingFace Datasets)
-- ============================================================================

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hf_id TEXT NOT NULL UNIQUE,
    owner TEXT,
    name TEXT NOT NULL,
    description TEXT,
    card_content TEXT,
    tags JSONB DEFAULT '[]',
    languages JSONB DEFAULT '[]',
    license TEXT,
    downloads BIGINT DEFAULT 0,
    likes INTEGER DEFAULT 0,
    features JSONB DEFAULT '{}',
    splits JSONB DEFAULT '{}',
    dataset_size_bytes BIGINT DEFAULT 0,
    is_public BOOLEAN DEFAULT TRUE,
    indexed_by UUID,
    chunk_count INTEGER DEFAULT 0,
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_datasets_hf_id ON datasets(hf_id);
CREATE INDEX IF NOT EXISTS idx_datasets_public ON datasets(is_public);

CREATE TABLE IF NOT EXISTS user_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_user_datasets_user ON user_datasets(user_id);

CREATE TABLE IF NOT EXISTS dataset_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    section_title TEXT,
    chunk_type TEXT DEFAULT 'card',
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(dataset_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_dataset_chunks_dataset ON dataset_chunks(dataset_id);

CREATE TABLE IF NOT EXISTS dataset_chunk_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES dataset_chunks(chunk_id) ON DELETE CASCADE UNIQUE,
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_dataset ON dataset_chunk_embeddings(dataset_id);
CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_vector ON dataset_chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ============================================================================
-- PART 17: INDEXING JOBS (Background Job Queue)
-- ============================================================================

CREATE TABLE IF NOT EXISTS indexing_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Job owner
    user_id UUID NOT NULL,

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


-- ============================================================================
-- PART 18: ACTIVITY LOG (Per-User)
-- ============================================================================

CREATE TABLE IF NOT EXISTS activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
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


-- ============================================================================
-- PART 19: HELPER FUNCTIONS
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
$$ LANGUAGE plpgsql;


-- Check if repo already indexed (for deduplication)
CREATE OR REPLACE FUNCTION get_existing_repo(p_url TEXT, p_branch TEXT)
RETURNS UUID AS $$
    SELECT repo_id FROM repositories WHERE url = p_url AND branch = p_branch;
$$ LANGUAGE sql;


-- Check if paper already indexed (for deduplication)
CREATE OR REPLACE FUNCTION get_existing_paper(p_pdf_hash TEXT)
RETURNS UUID AS $$
    SELECT paper_id FROM papers WHERE pdf_hash = p_pdf_hash;
$$ LANGUAGE sql;


-- Add repo to user's collection
CREATE OR REPLACE FUNCTION add_repo_to_user(p_user_id UUID, p_repo_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO user_repositories (user_id, repo_id)
    VALUES (p_user_id, p_repo_id)
    ON CONFLICT (user_id, repo_id) DO UPDATE SET last_searched_at = NOW();
END;
$$ LANGUAGE plpgsql;


-- Add paper to user's collection
CREATE OR REPLACE FUNCTION add_paper_to_user(p_user_id UUID, p_paper_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO user_papers (user_id, paper_id)
    VALUES (p_user_id, p_paper_id)
    ON CONFLICT (user_id, paper_id) DO UPDATE SET last_searched_at = NOW();
END;
$$ LANGUAGE plpgsql;


-- Search code chunks
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
$$ LANGUAGE plpgsql;


-- Search paper chunks
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
$$ LANGUAGE plpgsql;


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
$$ LANGUAGE plpgsql;


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
$$ LANGUAGE plpgsql;


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
$$ LANGUAGE plpgsql;


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
$$ LANGUAGE plpgsql;


-- ============================================================================
-- LOCAL DEVELOPMENT DATA
-- ============================================================================

-- Create a default dev user
INSERT INTO users (id, email, name)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'dev@localhost',
    'Dev User'
)
ON CONFLICT (id) DO NOTHING;

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
    'users', 'api_keys', 'github_tokens', 'huggingface_tokens',
    'repositories', 'user_repositories', 'repository_files', 'code_chunks', 'chunk_embeddings', 'symbols',
    'papers', 'user_papers', 'paper_chunks', 'paper_chunk_embeddings', 'citations', 'equations', 'paper_code_snippets',
    'datasets', 'user_datasets', 'dataset_chunks', 'dataset_chunk_embeddings',
    'indexing_jobs', 'activity_log'
)
ORDER BY table_name;


-- ============================================================================
-- SETUP COMPLETE!
-- ============================================================================
--
-- Tables created:
--   Auth:
--   - users: Local user accounts
--   - api_keys: Authentication tokens
--
--   Code Context:
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
--
-- Next steps:
--   1. Set DATABASE_URL in your .env file
--   2. Deploy your backend and connect!
--
-- ============================================================================
