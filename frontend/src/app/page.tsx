"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken, setAccessToken } from "@/lib/api";

interface ServerConfig {
  github_oauth_enabled: boolean;
  system_password_enabled: boolean;
}

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Show both auth methods immediately; config fetch can hide irrelevant ones
  const [config, setConfig] = useState<ServerConfig>({ github_oauth_enabled: true, system_password_enabled: true });

  // If already authenticated, redirect to overview
  useEffect(() => {
    getAccessToken().then((token) => {
      if (token) router.replace("/overview");
    });
  }, [router]);

  // Fetch actual server config to refine which auth methods are shown
  useEffect(() => {
    fetch("/config")
      .then((r) => r.json())
      .then((data) => setConfig(data))
      .catch(() => {});
  }, []);

  function handleGitHubLogin() {
    // Redirect to backend OAuth endpoint (proxied via next.config rewrites)
    window.location.href = "/auth/github";
  }

  async function handlePasswordLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const resp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        setError(data.detail || "Invalid password");
        setLoading(false);
        return;
      }

      const data = await resp.json();
      setAccessToken(data.token);
      router.replace("/overview");
    } catch {
      setError("Could not connect to server");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f7f0e8] flex items-center justify-center">
      <div className="w-full max-w-sm p-8 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
        <h1 className="text-sm font-semibold text-[#2e2522] tracking-tight mb-1">
          delphi
        </h1>
        <p className="text-[11px] text-[#8a7a72] mb-6">
          Sign in to access your context server.
        </p>

        {/* GitHub OAuth */}
        {config.github_oauth_enabled && (
          <button
            type="button"
            onClick={handleGitHubLogin}
            className="w-full py-2.5 bg-[#2e2522] text-[#f7f0e8] text-xs font-medium rounded-md hover:bg-[#3a3230] transition-colors flex items-center justify-center gap-2 mb-4"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
            Sign in with GitHub
          </button>
        )}

        {/* Divider */}
        {config.github_oauth_enabled && config.system_password_enabled && (
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-px bg-[#dfcdbf]" />
            <span className="text-[10px] text-[#a09488] uppercase">or</span>
            <div className="flex-1 h-px bg-[#dfcdbf]" />
          </div>
        )}

        {/* Password login */}
        {config.system_password_enabled && (
          <form onSubmit={handlePasswordLogin}>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="System password"
              autoFocus={!config.github_oauth_enabled}
              className="w-full px-3 py-2 bg-[#f7f0e8] border border-[#dfcdbf] rounded-md text-sm text-[#2e2522] placeholder-[#a09488] focus:outline-none focus:border-[#c5b5a5] mb-3"
            />

            {error && (
              <p className="text-[11px] text-red-400 mb-3">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              className="w-full py-2 bg-[#b58a73] text-[#f7f0e8] text-xs font-medium rounded-md hover:bg-[#a07a63] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Authenticating..." : "Log in with password"}
            </button>
          </form>
        )}

        {/* No auth configured */}
        {config && !config.github_oauth_enabled && !config.system_password_enabled && (
          <p className="text-[11px] text-red-400">
            No authentication method configured. Set GITHUB_CLIENT_ID + GITHUB_CLIENT_SECRET or SYSTEM_PASSWORD.
          </p>
        )}
      </div>
    </div>
  );
}
