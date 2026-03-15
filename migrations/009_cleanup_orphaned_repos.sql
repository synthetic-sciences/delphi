-- =============================================================================
-- Migration 009: Cleanup Orphaned Repositories
-- =============================================================================
--
-- Addresses data consistency issue where server crashes during indexing could
-- leave orphaned repositories (repos without user_repositories entries).
--
-- This migration:
-- 1. Creates a function to find orphaned repositories
-- 2. Creates a function to clean up orphaned repositories
-- 3. Creates a check constraint to prevent future orphans (optional)
--
-- Run this in your Supabase SQL Editor
-- =============================================================================

-- Function to find orphaned private repositories
-- (private repos without any user_repositories entries)
CREATE OR REPLACE FUNCTION find_orphaned_repositories()
RETURNS TABLE(
    repo_id UUID,
    owner TEXT,
    name TEXT,
    branch TEXT,
    indexed_by UUID,
    indexed_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.repo_id,
        r.owner,
        r.name,
        r.branch,
        r.indexed_by,
        r.indexed_at
    FROM repositories r
    LEFT JOIN user_repositories ur ON r.repo_id = ur.repo_id
    WHERE
        ur.repo_id IS NULL
        AND r.is_public = FALSE  -- Only private repos should always have a user_repositories entry
        AND r.indexed_at < NOW() - INTERVAL '5 minutes';  -- Ignore recent ones (might still be indexing)
END;
$$ LANGUAGE plpgsql;

-- Function to clean up orphaned repositories
-- Returns the number of repos deleted
CREATE OR REPLACE FUNCTION cleanup_orphaned_repositories()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Find and delete orphaned private repositories
    WITH orphaned AS (
        SELECT r.repo_id
        FROM repositories r
        LEFT JOIN user_repositories ur ON r.repo_id = ur.repo_id
        WHERE
            ur.repo_id IS NULL
            AND r.is_public = FALSE
            AND r.indexed_at < NOW() - INTERVAL '5 minutes'
    ),
    deleted_chunks AS (
        DELETE FROM code_chunks
        WHERE repo_id IN (SELECT repo_id FROM orphaned)
    ),
    deleted_embeddings AS (
        DELETE FROM chunk_embeddings
        WHERE chunk_id IN (
            SELECT chunk_id FROM code_chunks
            WHERE repo_id IN (SELECT repo_id FROM orphaned)
        )
    ),
    deleted_symbols AS (
        DELETE FROM symbols
        WHERE repo_id IN (SELECT repo_id FROM orphaned)
    ),
    deleted_files AS (
        DELETE FROM repository_files
        WHERE repo_id IN (SELECT repo_id FROM orphaned)
    ),
    deleted_repos AS (
        DELETE FROM repositories
        WHERE repo_id IN (SELECT repo_id FROM orphaned)
        RETURNING 1
    )
    SELECT COUNT(*) INTO deleted_count FROM deleted_repos;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Add a comment explaining the cleanup process
COMMENT ON FUNCTION find_orphaned_repositories() IS
'Finds private repositories without user_repositories entries (orphaned due to crashes during indexing)';

COMMENT ON FUNCTION cleanup_orphaned_repositories() IS
'Deletes orphaned private repositories and all related data (chunks, embeddings, symbols, files)';

-- Create a scheduled cleanup job (runs daily at 2 AM UTC)
-- Note: This requires pg_cron extension which may not be available on all Supabase plans
-- If pg_cron is not available, you can run this manually or via a cron job in your application
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        -- Schedule daily cleanup at 2 AM UTC
        PERFORM cron.schedule(
            'cleanup-orphaned-repos',
            '0 2 * * *',  -- Daily at 2 AM
            'SELECT cleanup_orphaned_repositories();'
        );
    END IF;
END $$;

-- Manual cleanup: Run this to clean up any existing orphaned repositories
-- Uncomment the line below to run cleanup immediately:
-- SELECT cleanup_orphaned_repositories();

-- To check for orphaned repos before cleanup:
-- SELECT * FROM find_orphaned_repositories();
