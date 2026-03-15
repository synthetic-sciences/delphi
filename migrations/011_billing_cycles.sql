-- Migration: Add billing cycle tracking for monthly credit resets
-- Purpose: Track which billing cycle each cost belongs to for paid tier users
-- Free tier: One-time credits (cumulative all-time usage)
-- Paid tiers: Monthly recurring credits (usage resets each cycle)

-- Add billing_cycle column to track monthly cycles (format: YYYY-MM)
ALTER TABLE gemini_costs
ADD COLUMN IF NOT EXISTS billing_cycle TEXT;

-- Backfill existing records to current month (2026-02)
UPDATE gemini_costs
SET billing_cycle = TO_CHAR(created_at, 'YYYY-MM')
WHERE billing_cycle IS NULL;

-- Index for fast cycle-based queries (paid tier users)
CREATE INDEX IF NOT EXISTS idx_gemini_costs_cycle
ON gemini_costs(user_id, billing_cycle);

-- Drop existing function with CASCADE (removes all versions and dependencies)
DROP FUNCTION IF EXISTS public.get_gemini_cost_summary CASCADE;

-- Create new function with billing cycle support
CREATE OR REPLACE FUNCTION get_gemini_cost_summary(
    p_user_id TEXT,
    p_since TIMESTAMPTZ DEFAULT NULL,
    p_billing_cycle TEXT DEFAULT NULL
)
RETURNS TABLE(total_cost_usd NUMERIC) AS $$
BEGIN
    RETURN QUERY
    SELECT COALESCE(SUM(cost_usd), 0)::NUMERIC as total_cost_usd
    FROM gemini_costs
    WHERE user_id = p_user_id
      AND (p_since IS NULL OR created_at >= p_since)
      AND (p_billing_cycle IS NULL OR billing_cycle = p_billing_cycle);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION get_gemini_cost_summary TO authenticated;
GRANT EXECUTE ON FUNCTION get_gemini_cost_summary TO service_role;
GRANT EXECUTE ON FUNCTION get_gemini_cost_summary TO anon;
