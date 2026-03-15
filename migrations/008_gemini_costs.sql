-- Migration 008: Gemini API cost tracking
-- Per-user tracking of embedding API token usage and USD cost.

-- ============================================================================
-- Table: gemini_costs
-- ============================================================================

CREATE TABLE IF NOT EXISTS gemini_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- What triggered this cost
    operation TEXT NOT NULL,         -- 'index_repository', 'search_code'
    resource_id UUID,               -- repo_id (for indexing) or NULL (for search)

    -- Token + cost accounting
    token_count INTEGER NOT NULL,
    cost_usd NUMERIC(12, 8) NOT NULL,

    -- Context
    model TEXT NOT NULL DEFAULT 'gemini-embedding-001',
    batch_count INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gemini_costs_user ON gemini_costs(user_id);
CREATE INDEX IF NOT EXISTS idx_gemini_costs_created ON gemini_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_gemini_costs_operation ON gemini_costs(operation);

-- ============================================================================
-- Row Level Security
-- ============================================================================

ALTER TABLE gemini_costs ENABLE ROW LEVEL SECURITY;

-- Users can read their own cost entries
CREATE POLICY "gemini_costs_select" ON gemini_costs
    FOR SELECT USING (user_id = auth.uid());

-- Users can insert their own cost entries
CREATE POLICY "gemini_costs_insert" ON gemini_costs
    FOR INSERT WITH CHECK (user_id = auth.uid());

-- Service role has full access (backend inserts on behalf of users)
CREATE POLICY "gemini_costs_service" ON gemini_costs
    FOR ALL TO service_role USING (true);

-- ============================================================================
-- RPC: get_gemini_cost_summary
-- Server-side aggregation for cost summary endpoint.
-- ============================================================================

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
