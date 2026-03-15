-- ============================================================================
-- Migration 014: Revoke authenticated access to SECURITY DEFINER functions
-- ============================================================================
-- All RPC functions are called by the backend (service_role), never by the
-- frontend client. Revoking EXECUTE from authenticated prevents any user
-- with a JWT from calling these functions directly with arbitrary parameters.
--
-- Risk addressed: SECURITY DEFINER functions accept a p_user_id parameter
-- and run as postgres (bypassing RLS). An authenticated user could call
-- e.g. create_api_key(other_user_id) or add_repo_to_user(other_user_id, ...).
-- ============================================================================

-- ============================================================================
-- STEP 1: Revoke all function EXECUTE from authenticated
-- ============================================================================

-- API key creation — accepts arbitrary user_id, inserts as postgres
REVOKE EXECUTE ON FUNCTION create_api_key FROM authenticated;

-- Dedup lookups — leak repo_id/paper_id of any resource (including private)
REVOKE EXECUTE ON FUNCTION get_existing_repo FROM authenticated;
REVOKE EXECUTE ON FUNCTION get_existing_paper FROM authenticated;

-- Collection management — can inject into any user's collection
REVOKE EXECUTE ON FUNCTION add_repo_to_user FROM authenticated;
REVOKE EXECUTE ON FUNCTION add_paper_to_user FROM authenticated;
REVOKE EXECUTE ON FUNCTION add_dataset_to_user FROM authenticated;

-- Search functions — accept arbitrary user_id, bypass RLS via SECURITY DEFINER
REVOKE EXECUTE ON FUNCTION search_code FROM authenticated;
REVOKE EXECUTE ON FUNCTION search_papers FROM authenticated;
REVOKE EXECUTE ON FUNCTION match_paper_chunks FROM authenticated;
REVOKE EXECUTE ON FUNCTION match_dataset_chunks FROM authenticated;

-- Listing functions — can list any user's repos/papers
REVOKE EXECUTE ON FUNCTION list_user_repos FROM authenticated;
REVOKE EXECUTE ON FUNCTION list_user_papers FROM authenticated;

-- Cost summary — function may not exist (migration 011 DROP CASCADE may have
-- removed it without successful re-creation). Guard with DO block.
DO $$ BEGIN
    REVOKE EXECUTE ON FUNCTION get_gemini_cost_summary(TEXT, TIMESTAMPTZ, TEXT) FROM authenticated;
    REVOKE EXECUTE ON FUNCTION get_gemini_cost_summary(TEXT, TIMESTAMPTZ, TEXT) FROM anon;
EXCEPTION WHEN undefined_function THEN
    NULL; -- function doesn't exist, nothing to revoke
END $$;

-- GitHub ID lookup — reads auth.identities for any user
REVOKE EXECUTE ON FUNCTION get_github_id FROM authenticated;

-- Worker functions — should already be service_role only, but be explicit
REVOKE EXECUTE ON FUNCTION claim_next_job FROM authenticated;
REVOKE EXECUTE ON FUNCTION update_job_progress FROM authenticated;

-- Rate limiting — backend-only
REVOKE EXECUTE ON FUNCTION check_rate_limit FROM authenticated;

-- ============================================================================
-- STEP 2: Ensure service_role retains access to everything
-- ============================================================================

GRANT EXECUTE ON FUNCTION create_api_key TO service_role;
GRANT EXECUTE ON FUNCTION get_existing_repo TO service_role;
GRANT EXECUTE ON FUNCTION get_existing_paper TO service_role;
GRANT EXECUTE ON FUNCTION add_repo_to_user TO service_role;
GRANT EXECUTE ON FUNCTION add_paper_to_user TO service_role;
GRANT EXECUTE ON FUNCTION add_dataset_to_user TO service_role;
GRANT EXECUTE ON FUNCTION search_code TO service_role;
GRANT EXECUTE ON FUNCTION search_papers TO service_role;
GRANT EXECUTE ON FUNCTION match_paper_chunks TO service_role;
GRANT EXECUTE ON FUNCTION match_dataset_chunks TO service_role;
GRANT EXECUTE ON FUNCTION list_user_repos TO service_role;
GRANT EXECUTE ON FUNCTION list_user_papers TO service_role;
DO $$ BEGIN
    GRANT EXECUTE ON FUNCTION get_gemini_cost_summary(TEXT, TIMESTAMPTZ, TEXT) TO service_role;
EXCEPTION WHEN undefined_function THEN
    NULL; -- function doesn't exist, skip
END $$;
GRANT EXECUTE ON FUNCTION get_github_id TO service_role;
GRANT EXECUTE ON FUNCTION claim_next_job TO service_role;
GRANT EXECUTE ON FUNCTION update_job_progress TO service_role;
GRANT EXECUTE ON FUNCTION check_rate_limit TO service_role;
