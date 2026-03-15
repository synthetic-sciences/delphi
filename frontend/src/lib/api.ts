/**
 * API client for Delphi (synsc-context) backend.
 *
 * Auth flow:
 *   1. User clicks "Login with GitHub" → redirected to GitHub OAuth.
 *   2. After OAuth, backend issues a JWT session token.
 *   3. Frontend stores the JWT in localStorage and sends it as Bearer token.
 *   4. Alternatively, admin can log in with SYSTEM_PASSWORD → also gets JWT.
 *   5. User creates API keys for AI agents via the dashboard.
 */

export const API_URL = "";

const DIRECT_API_URL = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Get a valid access token (JWT session token from localStorage).
 */
export async function getAccessToken(): Promise<string | null> {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("synsc_session_token");
    if (stored) return stored;
  }
  return null;
}

/**
 * Store a session token (JWT from OAuth or password login).
 */
export function setAccessToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("synsc_session_token", token);
  }
}

/**
 * Clear stored credentials (logout).
 */
export function clearAccessToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("synsc_session_token");
  }
}

/**
 * Get auth headers for direct fetch calls.
 */
export async function getAuthHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

async function apiFetch(
  path: string,
  options: RequestInit = {},
  useDirect = false
): Promise<Response> {
  const token = await getAccessToken();
  const base = useDirect ? DIRECT_API_URL : API_URL;
  const url = `${base}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(url, { ...options, headers });

  // If we get a 401, redirect to login
  if (resp.status === 401 && typeof window !== "undefined") {
    clearAccessToken();
    window.location.href = "/";
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
