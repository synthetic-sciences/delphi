-- ============================================================================
-- Migration 006: HuggingFace Dataset Indexing
-- ============================================================================
-- Stores HuggingFace dataset metadata and enables semantic search over
-- dataset cards (README documentation). Indexes metadata only — never
-- actual dataset rows.
-- ============================================================================

-- Main table: datasets
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- HuggingFace identity (dedup key)
    hf_id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,

    -- Metadata from HuggingFace Hub
    description TEXT,
    card_content TEXT,
    tags JSONB DEFAULT '[]',
    languages JSONB DEFAULT '[]',
    license TEXT,
    downloads INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,

    -- Structured schema info (from HF API, not downloaded data)
    features JSONB DEFAULT '{}',
    splits JSONB DEFAULT '{}',
    dataset_size_bytes BIGINT,

    -- Visibility & ownership
    is_public BOOLEAN DEFAULT TRUE,
    indexed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,

    -- Statistics
    chunk_count INTEGER DEFAULT 0,

    -- Timestamps
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_datasets_hf_id ON datasets(hf_id);
CREATE INDEX IF NOT EXISTS idx_datasets_owner ON datasets(owner);
CREATE INDEX IF NOT EXISTS idx_datasets_public ON datasets(is_public);
CREATE INDEX IF NOT EXISTS idx_datasets_indexed_by ON datasets(indexed_by);

ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "datasets_read" ON datasets;
CREATE POLICY "datasets_read" ON datasets FOR SELECT USING (
    is_public = TRUE OR indexed_by = auth.uid()
);
DROP POLICY IF EXISTS "datasets_insert" ON datasets;
CREATE POLICY "datasets_insert" ON datasets FOR INSERT WITH CHECK (
    indexed_by = auth.uid()
);
DROP POLICY IF EXISTS "datasets_update" ON datasets;
CREATE POLICY "datasets_update" ON datasets FOR UPDATE USING (
    indexed_by = auth.uid()
);
DROP POLICY IF EXISTS "datasets_delete" ON datasets;
CREATE POLICY "datasets_delete" ON datasets FOR DELETE USING (
    indexed_by = auth.uid()
);
DROP POLICY IF EXISTS "datasets_service" ON datasets;
CREATE POLICY "datasets_service" ON datasets FOR ALL TO service_role USING (true);


-- Junction table: user_datasets
CREATE TABLE IF NOT EXISTS user_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,

    notes TEXT,
    is_favorite BOOLEAN DEFAULT FALSE,

    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ,
    search_count INTEGER DEFAULT 0,

    UNIQUE(user_id, dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_user_datasets_user ON user_datasets(user_id);
CREATE INDEX IF NOT EXISTS idx_user_datasets_dataset ON user_datasets(dataset_id);

ALTER TABLE user_datasets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "user_datasets_policy" ON user_datasets;
CREATE POLICY "user_datasets_policy" ON user_datasets FOR ALL USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "user_datasets_service" ON user_datasets;
CREATE POLICY "user_datasets_service" ON user_datasets FOR ALL TO service_role USING (true);


-- Chunks table: dataset_chunks
CREATE TABLE IF NOT EXISTS dataset_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,

    chunk_index INTEGER NOT NULL,
    section_title TEXT,
    content TEXT NOT NULL,
    chunk_type TEXT DEFAULT 'section',
    token_count INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(dataset_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_dataset_chunks_dataset ON dataset_chunks(dataset_id);

ALTER TABLE dataset_chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "dataset_chunks_read" ON dataset_chunks;
CREATE POLICY "dataset_chunks_read" ON dataset_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM datasets d
        WHERE d.dataset_id = dataset_chunks.dataset_id
        AND (d.is_public = TRUE OR d.indexed_by = auth.uid())
    )
);
DROP POLICY IF EXISTS "dataset_chunks_service" ON dataset_chunks;
CREATE POLICY "dataset_chunks_service" ON dataset_chunks FOR ALL TO service_role USING (true);


-- Embeddings table: dataset_chunk_embeddings
CREATE TABLE IF NOT EXISTS dataset_chunk_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES dataset_chunks(chunk_id) ON DELETE CASCADE UNIQUE,
    dataset_id UUID NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_dataset ON dataset_chunk_embeddings(dataset_id);
CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_chunk ON dataset_chunk_embeddings(chunk_id);

CREATE INDEX IF NOT EXISTS idx_dataset_embeddings_vector ON dataset_chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE dataset_chunk_embeddings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "dataset_embeddings_read" ON dataset_chunk_embeddings;
CREATE POLICY "dataset_embeddings_read" ON dataset_chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM datasets d
        WHERE d.dataset_id = dataset_chunk_embeddings.dataset_id
        AND (d.is_public = TRUE OR d.indexed_by = auth.uid())
    )
);
DROP POLICY IF EXISTS "dataset_embeddings_service" ON dataset_chunk_embeddings;
CREATE POLICY "dataset_embeddings_service" ON dataset_chunk_embeddings FOR ALL TO service_role USING (true);


-- ============================================================================
-- RPC Functions
-- ============================================================================

-- Semantic search over dataset chunks (access-controlled via user_datasets)
CREATE OR REPLACE FUNCTION match_dataset_chunks(
    query_embedding vector(768),
    match_user_id uuid,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    chunk_id uuid,
    dataset_id uuid,
    chunk_index int,
    content text,
    section_title text,
    chunk_type text,
    dataset_name text,
    hf_id text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        dc.chunk_id,
        dc.dataset_id,
        dc.chunk_index,
        dc.content,
        dc.section_title,
        dc.chunk_type,
        d.name AS dataset_name,
        d.hf_id,
        1 - (dce.embedding <=> query_embedding) AS similarity
    FROM dataset_chunk_embeddings dce
    INNER JOIN dataset_chunks dc ON dce.chunk_id = dc.chunk_id
    INNER JOIN datasets d ON dc.dataset_id = d.dataset_id
    INNER JOIN user_datasets ud ON d.dataset_id = ud.dataset_id
    WHERE ud.user_id = match_user_id
    ORDER BY dce.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- Add dataset to user's collection
CREATE OR REPLACE FUNCTION add_dataset_to_user(p_user_id UUID, p_dataset_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO user_datasets (user_id, dataset_id)
    VALUES (p_user_id, p_dataset_id)
    ON CONFLICT (user_id, dataset_id) DO UPDATE SET last_searched_at = NOW();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Permissions
GRANT EXECUTE ON FUNCTION match_dataset_chunks TO authenticated;
GRANT EXECUTE ON FUNCTION match_dataset_chunks TO service_role;
GRANT EXECUTE ON FUNCTION add_dataset_to_user TO authenticated;
GRANT EXECUTE ON FUNCTION add_dataset_to_user TO service_role;
