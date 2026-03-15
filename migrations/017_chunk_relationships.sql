-- Migration 017: Chunk relationships table
-- Stores directed edges between code chunks for relationship-aware search.
-- Relationship types: 'adjacent', 'same_class'
-- Built at index time from symbol extraction data.

CREATE TABLE IF NOT EXISTS chunk_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_chunk_id UUID NOT NULL REFERENCES code_chunks(chunk_id) ON DELETE CASCADE,
    target_chunk_id UUID NOT NULL REFERENCES code_chunks(chunk_id) ON DELETE CASCADE,
    relationship_type VARCHAR(20) NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT unique_chunk_relationship
        UNIQUE (source_chunk_id, target_chunk_id, relationship_type)
);

-- Indexes for query-time lookup: given a chunk, find related chunks
CREATE INDEX IF NOT EXISTS idx_chunk_rel_source ON chunk_relationships(source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunk_rel_target ON chunk_relationships(target_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunk_rel_source_type
    ON chunk_relationships(source_chunk_id, relationship_type);
