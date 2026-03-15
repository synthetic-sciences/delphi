-- ============================================================================
-- Migration 015: Harden dataset RLS to require collection membership
-- ============================================================================
-- Migration 004 hardened repos and papers to require junction table membership
-- for SELECT access. Datasets (added in migration 006) still use the weaker
-- pattern: is_public = TRUE OR indexed_by = auth.uid().
--
-- This aligns datasets with the same pattern: you must either be the indexer
-- OR have the dataset in your user_datasets collection.
-- ============================================================================

-- ============================================================================
-- STEP 1: Harden datasets table
-- ============================================================================

DROP POLICY IF EXISTS "datasets_read" ON datasets;
CREATE POLICY "datasets_read" ON datasets FOR SELECT USING (
    indexed_by = auth.uid()
    OR EXISTS (
        SELECT 1 FROM user_datasets ud
        WHERE ud.user_id = auth.uid() AND ud.dataset_id = datasets.dataset_id
    )
);

-- ============================================================================
-- STEP 2: Harden dataset_chunks (inherit via collection membership)
-- ============================================================================

DROP POLICY IF EXISTS "dataset_chunks_read" ON dataset_chunks;
CREATE POLICY "dataset_chunks_read" ON dataset_chunks FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM datasets d
        WHERE d.dataset_id = dataset_chunks.dataset_id
        AND (
            d.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_datasets ud
                WHERE ud.user_id = auth.uid() AND ud.dataset_id = d.dataset_id
            )
        )
    )
);

-- ============================================================================
-- STEP 3: Harden dataset_chunk_embeddings (inherit via collection membership)
-- ============================================================================

DROP POLICY IF EXISTS "dataset_embeddings_read" ON dataset_chunk_embeddings;
CREATE POLICY "dataset_embeddings_read" ON dataset_chunk_embeddings FOR SELECT USING (
    EXISTS (
        SELECT 1 FROM datasets d
        WHERE d.dataset_id = dataset_chunk_embeddings.dataset_id
        AND (
            d.indexed_by = auth.uid()
            OR EXISTS (
                SELECT 1 FROM user_datasets ud
                WHERE ud.user_id = auth.uid() AND ud.dataset_id = d.dataset_id
            )
        )
    )
);
