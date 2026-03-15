import { createClient, SupabaseClient } from "@supabase/supabase-js";

/**
 * Singleton Supabase client.
 *
 * Reads NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY at
 * build/runtime.  The client automatically refreshes the JWT when it
 * expires, so callers always get a valid access_token.
 */

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

let _client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (_client) return _client;

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY"
    );
  }

  _client = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: true,       // uses localStorage by default
      autoRefreshToken: true,     // refresh before expiry
      detectSessionInUrl: true,   // pick up OAuth callback hash
    },
  });

  return _client;
}
