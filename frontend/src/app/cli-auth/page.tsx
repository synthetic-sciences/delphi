"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Github, CheckCircle2, Terminal, XCircle, Loader2 } from "lucide-react";

// Use relative URLs — requests go through Vercel/Next.js rewrites to avoid CORS
const apiUrl = "";

type AuthStage = "verify" | "authenticating" | "completing" | "done" | "error";

function CLIAuthContent() {
  const searchParams = useSearchParams();
  const cliCode = searchParams.get("cli_code") || "";

  const [stage, setStage] = useState<AuthStage>("verify");
  const [error, setError] = useState<string>("");
  const [userName, setUserName] = useState<string>("");

  // Complete the CLI auth session after GitHub OAuth
  const completeCLIAuth = useCallback(
    async (accessToken: string) => {
      if (!cliCode) {
        setError("No CLI code provided. Please run the CLI command again.");
        setStage("error");
        return;
      }

      setStage("completing");

      try {
        // Get user info from Supabase using the access token
        const configRes = await fetch(`${apiUrl}/config`);
        const config = await configRes.json();
        const supabaseUrl = config.supabase_url;

        let userNameVal = "";
        let userEmail = "";

        if (supabaseUrl && accessToken) {
          const userRes = await fetch(`${supabaseUrl}/auth/v1/user`, {
            headers: { Authorization: `Bearer ${accessToken}`, apikey: config.supabase_publishable_key || "" },
          });
          if (userRes.ok) {
            const userData = await userRes.json();
            userNameVal =
              userData.user_metadata?.full_name ||
              userData.user_metadata?.preferred_username ||
              userData.user_metadata?.name ||
              "";
            userEmail = userData.email || "";
          }
        }

        // Complete the CLI auth session on the backend
        // Send the access_token so the backend can verify it and extract user_id
        const res = await fetch(`${apiUrl}/api/cli/auth/complete`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_code: cliCode,
            access_token: accessToken,
            user_name: userNameVal,
            user_email: userEmail,
          }),
        });

        const data = await res.json();

        if (data.success) {
          setUserName(userNameVal);
          setStage("done");
        } else {
          setError(data.error || "Failed to complete authentication");
          setStage("error");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Network error");
        setStage("error");
      }
    },
    [cliCode]
  );

  // Handle OAuth callback — Supabase appends tokens to the URL hash
  useEffect(() => {
    if (typeof window === "undefined") return;

    const hash = window.location.hash;
    if (hash && hash.includes("access_token")) {
      const params = new URLSearchParams(hash.substring(1));
      const accessToken = params.get("access_token");

      if (accessToken) {
        // Clean the hash immediately
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        completeCLIAuth(accessToken);
      }
    }
  }, [completeCLIAuth]);

  async function handleGitHubLogin() {
    setStage("authenticating");

    try {
      const res = await fetch(`${apiUrl}/config`);
      if (!res.ok) throw new Error("Backend unavailable");
      const config = await res.json();

      const supabaseUrl = config.supabase_url;
      const supabaseKey = config.supabase_publishable_key;

      if (!supabaseUrl || !supabaseKey) {
        setError("Authentication is not configured on the server.");
        setStage("error");
        return;
      }

      // Redirect back to this same page with the cli_code preserved
      const redirectTo = encodeURIComponent(
        `${window.location.origin}/cli-auth?cli_code=${encodeURIComponent(cliCode)}`
      );
      const oauthUrl = `${supabaseUrl}/auth/v1/authorize?provider=github&redirect_to=${redirectTo}`;
      window.location.href = oauthUrl;
    } catch {
      setError("Could not connect to the backend. Please try again.");
      setStage("error");
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
      <div className="w-full max-w-md mx-4">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <svg width="40" height="40" viewBox="0 0 100 100" fill="none" className="mb-4">
            <circle cx="50" cy="50" r="8" fill="#fa7315" />
            <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none" />
            <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none" transform="rotate(60 50 50)" />
            <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none" transform="rotate(120 50 50)" />
          </svg>
          <h1 className="text-xl font-medium text-white lowercase tracking-wide">synthetic sciences</h1>
          <p className="text-sm text-[#555] mt-1 lowercase">cli authentication</p>
        </div>

        {/* ─── Stage: Verify Code ─── */}
        {stage === "verify" && (
          <div className="p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a]">
            {/* Show the CLI code */}
            {cliCode && (
              <div className="mb-6">
                <p className="text-xs text-[#555] mb-2 lowercase">verification code from your terminal</p>
                <div className="flex items-center justify-center gap-2 py-4 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a]">
                  <Terminal size={16} className="text-[#fa7315]" />
                  <span className="text-2xl font-mono font-bold tracking-[0.3em] text-white">{cliCode}</span>
                </div>
                <p className="text-[10px] text-[#333] mt-2 text-center lowercase">
                  make sure this matches the code shown in your terminal
                </p>
              </div>
            )}

            {!cliCode && (
              <div className="mb-6 p-4 rounded-xl bg-red-500/5 border border-red-500/20">
                <p className="text-sm text-red-400 lowercase">
                  no verification code found. please run{" "}
                  <code className="px-1.5 py-0.5 rounded bg-[#1a1a1a] text-[#fa7315] text-xs">npx synsc-context-keys</code>{" "}
                  in your terminal first.
                </p>
              </div>
            )}

            <h2 className="text-sm font-medium text-white mb-1 lowercase">sign in to continue</h2>
            <p className="text-xs text-[#555] mb-5 lowercase">
              authenticate with github to link your account and generate an api key for the cli.
            </p>

            <button
              onClick={handleGitHubLogin}
              disabled={!cliCode}
              className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-white text-black text-sm font-medium rounded-lg lowercase hover:bg-[#eee] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <Github size={18} />
              continue with github
            </button>
          </div>
        )}

        {/* ─── Stage: Authenticating ─── */}
        {stage === "authenticating" && (
          <div className="p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] text-center">
            <Loader2 size={24} className="text-[#fa7315] animate-spin mx-auto mb-4" />
            <p className="text-sm text-[#555] lowercase">redirecting to github…</p>
          </div>
        )}

        {/* ─── Stage: Completing ─── */}
        {stage === "completing" && (
          <div className="p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] text-center">
            <Loader2 size={24} className="text-[#fa7315] animate-spin mx-auto mb-4" />
            <p className="text-sm text-white lowercase mb-1">setting up your api key…</p>
            <p className="text-xs text-[#555] lowercase">this will only take a moment</p>
          </div>
        )}

        {/* ─── Stage: Done ─── */}
        {stage === "done" && (
          <div className="p-6 rounded-2xl bg-[#0f0f0f] border border-[#0f5132]">
            <div className="flex flex-col items-center text-center">
              <CheckCircle2 size={40} className="text-emerald-400 mb-4" />
              <h2 className="text-lg font-medium text-white lowercase mb-1">
                {userName ? `welcome, ${userName.toLowerCase()}!` : "authentication complete!"}
              </h2>
              <p className="text-sm text-[#555] lowercase mb-6">
                your api key has been generated and sent to the cli.
              </p>

              <div className="w-full p-4 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a] mb-4">
                <div className="flex items-center gap-2 justify-center">
                  <Terminal size={16} className="text-emerald-400" />
                  <p className="text-sm text-white lowercase">go back to your terminal</p>
                </div>
                <p className="text-xs text-[#555] mt-1 lowercase">
                  the cli will automatically pick up your api key
                </p>
              </div>

              <p className="text-[10px] text-[#333] lowercase">you can close this tab</p>
            </div>
          </div>
        )}

        {/* ─── Stage: Error ─── */}
        {stage === "error" && (
          <div className="p-6 rounded-2xl bg-[#0f0f0f] border border-red-500/20">
            <div className="flex flex-col items-center text-center">
              <XCircle size={40} className="text-red-400 mb-4" />
              <h2 className="text-sm font-medium text-white lowercase mb-1">authentication failed</h2>
              <p className="text-xs text-red-400/80 lowercase mb-5">{error}</p>

              <button
                onClick={() => {
                  setError("");
                  setStage("verify");
                }}
                className="px-6 py-2.5 bg-[#1a1a1a] text-white text-sm rounded-lg lowercase hover:bg-[#222] transition-colors"
              >
                try again
              </button>
            </div>
          </div>
        )}

        <p className="text-center text-[10px] text-[#333] mt-6 lowercase">
          by signing in you agree to our terms of service
        </p>
      </div>
    </div>
  );
}

export default function CLIAuthPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
          <Loader2 size={24} className="text-[#fa7315] animate-spin" />
        </div>
      }
    >
      <CLIAuthContent />
    </Suspense>
  );
}
