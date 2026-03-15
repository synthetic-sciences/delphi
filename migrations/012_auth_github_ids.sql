-- Migration 012: RPC to get github_id from auth identity data
--
-- Supabase stores GitHub OAuth identity data in auth.identities.
-- Since auth schema isn't accessible via PostgREST, this function
-- provides a clean way to resolve user_id → github_id.

CREATE OR REPLACE FUNCTION public.get_github_id(p_user_id UUID)
RETURNS BIGINT
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT (i.identity_data ->> 'sub')::bigint
    FROM auth.identities i
    WHERE i.user_id = p_user_id
      AND i.provider = 'github'
    LIMIT 1;
$$;
