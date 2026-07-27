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

// Browser requests must remain same-origin so the httpOnly session cookie set
// through the Next.js proxy is sent consistently in local, container, and
// split-host deployments. The server-side rewrite still uses
// INTERNAL_API_URL/NEXT_PUBLIC_API_URL to reach the backend.
export const DIRECT_API_URL = API_URL;

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
export function setAccessToken(token: string): void {
  void token;
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
  branch?: string,
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
    { method: "POST", body: JSON.stringify({ url: source }) },
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
  return apiFetch("/v1/symbols/search", {
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
// Unified workspace
// ---------------------------------------------------------------------------

export interface ProviderDescriptor {
  name: string;
  version?: string;
  capabilities: string[];
  execution?: string;
  accepted_classifications?: string[];
  health?: string;
}

export interface ConnectorSource {
  source_id: string;
  provider: string;
  display_name: string;
  classification?: string;
  enabled: boolean;
  schedule_seconds?: number | null;
  last_synced_at?: string | null;
  last_snapshot_id?: string | null;
  last_error?: string | null;
  updated_at?: string | null;
}

export interface ResearchSession {
  session_id: string;
  query: string;
  mode: string;
  status: string;
  created_at?: string | number | null;
  completed_at?: string | number | null;
}

export interface ContextSession {
  session_id: string;
  name: string;
  objective: string;
  status: string;
  sharing_policy: string;
  current_revision: number;
  write_version: number;
  parent_session_id?: string | null;
  expires_at?: string | null;
  updated_at?: string | null;
}

export interface WorkspaceSnapshot {
  providers: ProviderDescriptor[];
  connectorProviders: ProviderDescriptor[];
  connectors: ConnectorSource[];
  researchSessions: ResearchSession[];
  contextSessions: ContextSession[];
  unavailable: string[];
}

interface CollectionRequest {
  label: string;
  path: string;
  key: string;
}

async function fetchWorkspaceCollection<T>(
  request: CollectionRequest
): Promise<{ label: string; values: T[]; available: boolean }> {
  try {
    const response = await apiFetch(request.path);
    if (!response.ok) {
      return { label: request.label, values: [], available: false };
    }
    const payload = (await response.json()) as Record<string, unknown>;
    const value = payload[request.key];
    return {
      label: request.label,
      values: Array.isArray(value) ? (value as T[]) : [],
      available: true,
    };
  } catch {
    return { label: request.label, values: [], available: false };
  }
}

export async function getWorkspaceSnapshot(): Promise<WorkspaceSnapshot> {
  const [providers, connectorProviders, connectors, research, contexts] =
    await Promise.all([
      fetchWorkspaceCollection<ProviderDescriptor>({
        label: "providers",
        path: "/v2/providers",
        key: "providers",
      }),
      fetchWorkspaceCollection<ProviderDescriptor>({
        label: "connector providers",
        path: "/v2/connectors/providers",
        key: "providers",
      }),
      fetchWorkspaceCollection<ConnectorSource>({
        label: "connector sources",
        path: "/v2/connectors?limit=100",
        key: "sources",
      }),
      fetchWorkspaceCollection<ResearchSession>({
        label: "research sessions",
        path: "/v2/research?limit=50",
        key: "sessions",
      }),
      fetchWorkspaceCollection<ContextSession>({
        label: "context sessions",
        path: "/v2/context-sessions?limit=100",
        key: "sessions",
      }),
    ]);

  const results = [
    providers,
    connectorProviders,
    connectors,
    research,
    contexts,
  ];

  return {
    providers: providers.values,
    connectorProviders: connectorProviders.values,
    connectors: connectors.values,
    researchSessions: research.values,
    contextSessions: contexts.values,
    unavailable: results
      .filter((result) => !result.available)
      .map((result) => result.label),
  };
}

export async function syncConnectorSource(sourceId: string, priority = 0) {
  return apiFetch(`/v2/connectors/${encodeURIComponent(sourceId)}/sync`, {
    method: "POST",
    body: JSON.stringify({ priority }),
  });
}

export async function exportContextSession(sessionId: string) {
  return apiFetch(
    `/v2/context-sessions/${encodeURIComponent(sessionId)}/export`
  );
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
