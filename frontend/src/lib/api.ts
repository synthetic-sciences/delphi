/**
 * API client for synsc-context backend
 *
 * Uses the Supabase client for auth so tokens are auto-refreshed.
 */

import { getSupabase } from "./supabase";

// Use relative URLs so browser requests go through Vercel/Next.js rewrites (no CORS).
// NEXT_PUBLIC_API_URL is only used in next.config.mjs to configure the rewrite destination.
const API_URL = "";

// Direct backend URL for long-running requests (paper/repo indexing) that exceed
// Vercel's proxy timeout (~60s). These bypass the proxy and hit Render directly.
const DIRECT_API_URL = process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Get a valid access token.
 *
 * Priority:
 *   1. Supabase session (auto-refreshed JWT)
 *   2. Explicit API key in localStorage (`synsc_api_key` starting with `synsc_`)
 *   3. Dev fallback key in local development
 */
export async function getAccessToken(): Promise<string | null> {
  // 1) Supabase session — always fresh
  try {
    const { data } = await getSupabase().auth.getSession();
    const token = data.session?.access_token;
    if (token) return token;
  } catch {
    // Supabase not configured / SSR — fall through
  }

  // 2) Explicit custom API key (e.g. `synsc_894f…`)
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("synsc_api_key");
    if (stored && stored.startsWith("synsc_")) return stored;
  }

  // 3) Dev fallback
  if (process.env.NODE_ENV === "development") {
    return (
      process.env.NEXT_PUBLIC_DEV_API_KEY ||
      "synsc_dev_key_for_local_testing_only_do_not_use_in_production"
    );
  }

  return null;
}

/** Synchronous version — reads cached key (may be stale). Prefer getAccessToken(). */
export function getApiKey(): string | null {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("synsc_api_key");
    if (stored) return stored;
  }
  if (process.env.NODE_ENV === "development") {
    return (
      process.env.NEXT_PUBLIC_DEV_API_KEY ||
      "synsc_dev_key_for_local_testing_only_do_not_use_in_production"
    );
  }
  return null;
}

/**
 * Make an authenticated API request
 */
export async function api<T = unknown>(
  endpoint: string,
  options: RequestInit = {}
): Promise<{ ok: boolean; data?: T; error?: string; status: number }> {
  const token = await getAccessToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      const errorText = await res.text();
      return {
        ok: false,
        error: errorText || `HTTP ${res.status}`,
        status: res.status,
      };
    }

    // Handle empty responses
    const text = await res.text();
    const data = text ? JSON.parse(text) : undefined;

    return { ok: true, data, status: res.status };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Network error",
      status: 0,
    };
  }
}

/**
 * Convenience methods
 */
export const apiGet = <T = unknown>(endpoint: string) =>
  api<T>(endpoint, { method: "GET" });

export const apiPost = <T = unknown>(endpoint: string, body?: unknown) =>
  api<T>(endpoint, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });

export const apiDelete = <T = unknown>(endpoint: string) =>
  api<T>(endpoint, { method: "DELETE" });

/**
 * Get auth headers for raw fetch() calls.
 * Async because it may need to refresh the Supabase session.
 */
export async function getAuthHeaders(): Promise<HeadersInit> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export { API_URL, DIRECT_API_URL };
