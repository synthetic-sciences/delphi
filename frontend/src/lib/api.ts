/**
 * API client for Delphi (synsc-context) backend.
 *
 * Auth flow:
 *   1. User clicks "Login with GitHub" → redirected to GitHub OAuth.
 *   2. After OAuth, backend sets an httpOnly session cookie.
 *   3. All API requests include the cookie automatically via credentials: "include".
 *   4. Alternatively, admin can log in with SYSTEM_PASSWORD → also sets cookie.
 *   5. AI agents/MCP tools use API keys via Authorization header (no cookie).
 */

export const API_URL = "";

export const DIRECT_API_URL = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Check if user has a valid session.
 *
 * Uses /auth/check which never returns 401 — avoids noisy logs.
 */
export async function isAuthenticated(): Promise<boolean> {
  try {
    const resp = await fetch("/auth/check", { credentials: "include" });
    if (!resp.ok) return false;
    const data = await resp.json();
    return data.authenticated === true;
  } catch {
    return false;
  }
}

/**
 * Legacy getAccessToken — returns null since tokens are now in httpOnly cookies.
 * Kept for backward compatibility with components that check for a token.
 */
export async function getAccessToken(): Promise<string | null> {
  return null;
}

/**
 * Legacy setAccessToken — no-op since cookies are set by the backend.
 */
export function setAccessToken(_token: string): void {
  // No-op: session is managed via httpOnly cookie set by the backend.
}

/**
 * Clear session by calling the logout endpoint (which clears the cookie).
 */
export async function clearAccessToken(): Promise<void> {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
  } catch {
    // Best effort
  }
}

/**
 * Get auth headers for direct fetch calls (API keys only, not cookies).
 */
export async function getAuthHeaders(): Promise<Record<string, string>> {
  return { "Content-Type": "application/json" };
}

async function apiFetch(
  path: string,
  options: RequestInit = {},
  useDirect = false
): Promise<Response> {
  const base = useDirect ? DIRECT_API_URL : API_URL;
  const url = `${base}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const resp = await fetch(url, {
    ...options,
    headers,
    credentials: "include",  // Send httpOnly session cookie
  });

  // If we get a 401, redirect to login (but not if already on login page)
  if (resp.status === 401 && typeof window !== "undefined") {
    if (window.location.pathname !== "/") {
      window.location.href = "/";
    }
  }

  return resp;
}

// ---------------------------------------------------------------------------
// Repositories
// ---------------------------------------------------------------------------

export async function indexRepository(
  url: string,
  branch = "main",
  deepIndex = false
) {
  return apiFetch(
    "/v1/repositories/index",
    {
      method: "POST",
      body: JSON.stringify({ url, branch, deep_index: deepIndex }),
    },
    true
  );
}

export async function listRepositories(limit = 50, offset = 0) {
  return apiFetch(`/v1/repositories?limit=${limit}&offset=${offset}`);
}

export async function getRepository(repoId: string) {
  return apiFetch(`/v1/repositories/${repoId}`);
}

export async function deleteRepository(repoId: string) {
  return apiFetch(`/v1/repositories/${repoId}`, { method: "DELETE" });
}

export async function reindexRepository(repoId: string, force = false, deepIndex = false) {
  return apiFetch(`/v1/repositories/${repoId}/reindex`, {
    method: "POST",
    body: JSON.stringify({ force, deep_index: deepIndex }),
  });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export async function searchCode(
  query: string,
  repoIds?: string[],
  language?: string,
  topK = 10
) {
  return apiFetch("/v1/search/code", {
    method: "POST",
    body: JSON.stringify({
      query,
      repo_ids: repoIds,
      language,
      top_k: topK,
    }),
  });
}

// ---------------------------------------------------------------------------
// Papers
// ---------------------------------------------------------------------------

export async function indexPaper(source: string) {
  return apiFetch(
    "/v1/papers/index",
    { method: "POST", body: JSON.stringify({ source }) },
    true
  );
}

export async function listPapers(limit = 50) {
  return apiFetch(`/v1/papers?limit=${limit}`);
}

export async function getPaper(paperId: string) {
  return apiFetch(`/v1/papers/${paperId}`);
}

export async function searchPapers(query: string, topK = 10) {
  return apiFetch("/v1/search/papers", {
    method: "POST",
    body: JSON.stringify({ query, top_k: topK }),
  });
}

export async function deletePaper(paperId: string) {
  return apiFetch(`/v1/papers/${paperId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Datasets
// ---------------------------------------------------------------------------

export async function indexDataset(hfId: string) {
  return apiFetch(
    "/v1/datasets/index",
    { method: "POST", body: JSON.stringify({ hf_id: hfId }) },
    true
  );
}

export async function listDatasets(limit = 50) {
  return apiFetch(`/v1/datasets?limit=${limit}`);
}

export async function getDataset(datasetId: string) {
  return apiFetch(`/v1/datasets/${datasetId}`);
}

export async function deleteDataset(datasetId: string) {
  return apiFetch(`/v1/datasets/${datasetId}`, { method: "DELETE" });
}

export async function searchDatasets(query: string, topK = 10) {
  return apiFetch("/v1/search/datasets", {
    method: "POST",
    body: JSON.stringify({ query, top_k: topK }),
  });
}

// ---------------------------------------------------------------------------
// User / Profile
// ---------------------------------------------------------------------------

export async function getUserProfile() {
  return apiFetch("/v1/user/profile");
}

// ---------------------------------------------------------------------------
// Activity
// ---------------------------------------------------------------------------

export async function getActivity(limit = 50) {
  return apiFetch(`/v1/activity?limit=${limit}`);
}

// ---------------------------------------------------------------------------
// Symbols
// ---------------------------------------------------------------------------

export async function searchSymbols(
  name: string,
  repoIds?: string[],
  symbolType?: string,
  language?: string,
  topK = 25
) {
  return apiFetch("/v1/search/symbols", {
    method: "POST",
    body: JSON.stringify({
      name,
      repo_ids: repoIds,
      symbol_type: symbolType,
      language,
      top_k: topK,
    }),
  });
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function getHealth() {
  return apiFetch("/health");
}

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

export async function apiGet<T = unknown>(
  path: string,
  useDirect = false
): Promise<{ ok: boolean; data: T | null }> {
  try {
    const resp = await apiFetch(path, {}, useDirect);
    if (!resp.ok) return { ok: false, data: null };
    const data = await resp.json();
    return { ok: true, data };
  } catch {
    return { ok: false, data: null };
  }
}
