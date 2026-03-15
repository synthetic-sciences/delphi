"use client";

import PageShell from "@/components/PageShell";
import { useState, useEffect } from "react";
import {
  Key, Copy, Trash2, Plus, X, AlertTriangle,
  Check, Ban, RefreshCw, ExternalLink, Globe, Monitor,
  Github, Lock,
} from "lucide-react";
import Link from "next/link";
import { getAuthHeaders, API_URL } from "@/lib/api";

/* ── Token types ──────────────────────────────────────────── */
interface TokenInfo {
  has_token: boolean;
  label?: string;
  github_username?: string;
  last_used_at?: string;
  created_at?: string;
  updated_at?: string;
}

interface HFTokenInfo {
  has_token: boolean;
  label?: string;
  hf_username?: string;
  last_used_at?: string;
  created_at?: string;
  updated_at?: string;
}

/* ── Code block with copy button ────────────────────────────────────── */
function ConfigBlock({ code, lang = "json" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative group rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#1a1a1a]">
        <span className="text-[10px] text-[#333] uppercase tracking-wider">{lang}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="p-1 rounded hover:bg-[#1a1a1a] text-[#333] hover:text-[#888] transition-colors"
        >
          {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto text-xs font-mono text-[#999] leading-relaxed whitespace-pre">{code}</pre>
    </div>
  );
}

/* ── Usage config section with local/remote tabs ────────────────────── */
function UsageConfigSection() {
  const [mode, setMode] = useState<"http" | "stdio">("stdio");

  const httpConfig = `{
  "mcpServers": {
    "synsc-context": {
      "url": "http://localhost:8742/mcp",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}`;

  const stdioConfig = `{
  "mcpServers": {
    "synsc-context": {
      "command": "uvx",
      "args": ["synsc-context-proxy"],
      "env": {
        "SYNSC_API_KEY": "your_api_key_here"
      }
    }
  }
}`;

  return (
    <div className="mt-6 p-5 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
      <h3 className="text-xs text-[#555] font-medium uppercase tracking-wider mb-4">mcp configuration</h3>

      <p className="text-xs text-[#444] mb-4">
        add this to your agent&apos;s mcp config file to connect synsc context.
        replace <code className="text-[#fa7315]">your_api_key_here</code> with an active key from above.
      </p>

      {/* Mode tabs */}
      <div className="flex items-center gap-1 p-1 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] w-fit mb-4">
        <button
          onClick={() => setMode("stdio")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            mode === "stdio"
              ? "bg-[#fa7315] text-black"
              : "text-[#555] hover:text-white"
          }`}
        >
          <Monitor size={12} />
          local
        </button>
        <button
          onClick={() => setMode("http")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            mode === "http"
              ? "bg-[#fa7315] text-black"
              : "text-[#555] hover:text-white"
          }`}
        >
          <Globe size={12} />
          remote
        </button>
      </div>

      {/* Config block */}
      <ConfigBlock code={mode === "stdio" ? stdioConfig : httpConfig} lang="json" />

      {/* Explanation */}
      <div className="mt-3 p-3 rounded-lg bg-[#0f0f0f] border border-[#1a1a1a] text-xs text-[#555]">
        {mode === "stdio" ? (
          <p>
            <strong className="text-[#888]">how it works:</strong>{" "}
            <code className="text-[#fa7315]">uvx</code> installs a lightweight stdio proxy from pypi that runs locally
            and forwards all tool calls to the local backend with your api key.
            requires <code className="text-[#fa7315]">uv</code> (<code className="text-[#888]">curl -LsSf https://astral.sh/uv/install.sh | sh</code>).
          </p>
        ) : (
          <p>
            <strong className="text-[#888]">how it works:</strong> your agent connects directly to the local
            mcp endpoint over http. no local process needed. your client must support
            the <code className="text-[#fa7315]">streamable-http</code> transport.
          </p>
        )}
      </div>

      {/* Config file paths */}
      <div className="mt-4 space-y-1.5 text-[11px] text-[#444]">
        <p className="text-[10px] text-[#555] uppercase tracking-wider font-medium mb-2">config file locations</p>
        <div className="flex items-center gap-2">
          <span className="w-24 text-[#666]">cursor</span>
          <code className="text-[#888]">~/.cursor/mcp.json</code>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-24 text-[#666]">claude desktop</span>
          <code className="text-[#888]">~/Library/Application Support/Claude/claude_desktop_config.json</code>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-24 text-[#666]">claude code</span>
          <code className="text-[#888]">~/.claude/mcp.json</code>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-24 text-[#666]">windsurf</span>
          <code className="text-[#888]">~/.codeium/windsurf/mcp_config.json</code>
        </div>
      </div>
    </div>
  );
}

interface ApiKey {
  id: string;
  name: string;
  key_preview: string;
  is_revoked: boolean;
  last_used_at: string | null;
  created_at: string;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'never';
  return new Date(dateStr).toLocaleDateString();
}

function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRevealModal, setShowRevealModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [revealedKey, setRevealedKey] = useState('');
  const [copied, setCopied] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // GitHub PAT state
  const [tokenInfo, setTokenInfo] = useState<TokenInfo | null>(null);
  const [tokenLoading, setTokenLoading] = useState(true);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [labelInput, setLabelInput] = useState("");
  const [tokenSaving, setTokenSaving] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [tokenSuccess, setTokenSuccess] = useState<string | null>(null);

  // HuggingFace token state
  const [hfTokenInfo, setHfTokenInfo] = useState<HFTokenInfo | null>(null);
  const [hfTokenLoading, setHfTokenLoading] = useState(true);
  const [showHfTokenModal, setShowHfTokenModal] = useState(false);
  const [hfTokenInput, setHfTokenInput] = useState("");
  const [hfLabelInput, setHfLabelInput] = useState("");
  const [hfTokenSaving, setHfTokenSaving] = useState(false);
  const [hfTokenError, setHfTokenError] = useState<string | null>(null);
  const [hfTokenSuccess, setHfTokenSuccess] = useState<string | null>(null);

  // Fetch API keys + token status on mount
  useEffect(() => {
    fetchKeys();
    fetchTokenStatus();
    fetchHfTokenStatus();
  }, []);

  // Auto-clear token messages
  useEffect(() => {
    if (tokenSuccess || tokenError) {
      const t = setTimeout(() => { setTokenSuccess(null); setTokenError(null); }, 5000);
      return () => clearTimeout(t);
    }
  }, [tokenSuccess, tokenError]);

  useEffect(() => {
    if (hfTokenSuccess || hfTokenError) {
      const t = setTimeout(() => { setHfTokenSuccess(null); setHfTokenError(null); }, 5000);
      return () => clearTimeout(t);
    }
  }, [hfTokenSuccess, hfTokenError]);

  async function fetchKeys() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/keys`, { headers: await getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setKeys(data.keys || []);
      }
    } catch (error) {
      console.error('Failed to fetch keys:', error);
    } finally {
      setLoading(false);
    }
  }

  async function fetchTokenStatus() {
    setTokenLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/github/token`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        setTokenInfo(await res.json());
      }
    } catch (err) {
      console.error("Failed to fetch token status:", err);
    } finally {
      setTokenLoading(false);
    }
  }

  async function saveToken() {
    if (!tokenInput.trim()) return;
    setTokenSaving(true);
    setTokenError(null);
    setTokenSuccess(null);

    try {
      const res = await fetch(`${API_URL}/v1/github/token`, {
        method: "PUT",
        headers: await getAuthHeaders(),
        body: JSON.stringify({
          token: tokenInput.trim(),
          label: labelInput.trim() || null,
        }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        setTokenSuccess(`token saved for @${data.github_username}`);
        setShowTokenModal(false);
        setTokenInput("");
        setLabelInput("");
        fetchTokenStatus();
      } else {
        setTokenError(data.error || "failed to save token");
      }
    } catch {
      setTokenError("network error. please try again.");
    } finally {
      setTokenSaving(false);
    }
  }

  async function deleteToken() {
    if (!confirm("delete your github token? you won't be able to clone private repos until you add a new one.")) {
      return;
    }

    try {
      const res = await fetch(`${API_URL}/v1/github/token`, {
        method: "DELETE",
        headers: await getAuthHeaders(),
      });

      if (res.ok) {
        setTokenSuccess("token deleted");
        fetchTokenStatus();
      }
    } catch {
      setTokenError("failed to delete token");
    }
  }

  const hasToken = tokenInfo?.has_token ?? false;

  // HuggingFace token functions
  async function fetchHfTokenStatus() {
    setHfTokenLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/huggingface/token`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        setHfTokenInfo(await res.json());
      }
    } catch (err) {
      console.error("Failed to fetch HF token status:", err);
    } finally {
      setHfTokenLoading(false);
    }
  }

  async function saveHfToken() {
    if (!hfTokenInput.trim()) return;
    setHfTokenSaving(true);
    setHfTokenError(null);
    setHfTokenSuccess(null);

    try {
      const res = await fetch(`${API_URL}/v1/huggingface/token`, {
        method: "PUT",
        headers: await getAuthHeaders(),
        body: JSON.stringify({
          token: hfTokenInput.trim(),
          label: hfLabelInput.trim() || null,
        }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        setHfTokenSuccess(`token saved for ${data.hf_username}`);
        setShowHfTokenModal(false);
        setHfTokenInput("");
        setHfLabelInput("");
        fetchHfTokenStatus();
      } else {
        setHfTokenError(data.error || "failed to save token");
      }
    } catch {
      setHfTokenError("network error. please try again.");
    } finally {
      setHfTokenSaving(false);
    }
  }

  async function deleteHfToken() {
    if (!confirm("delete your huggingface token? you won't be able to index datasets until you add a new one.")) {
      return;
    }

    try {
      const res = await fetch(`${API_URL}/v1/huggingface/token`, {
        method: "DELETE",
        headers: await getAuthHeaders(),
      });

      if (res.ok) {
        setHfTokenSuccess("token deleted");
        fetchHfTokenStatus();
      }
    } catch {
      setHfTokenError("failed to delete token");
    }
  }

  const hasHfToken = hfTokenInfo?.has_token ?? false;

  async function createKey() {
    if (!newKeyName.trim()) return;
    
    setActionLoading('create');
    try {
      const res = await fetch(`${API_URL}/v1/keys`, {
        method: 'POST',
        headers: await getAuthHeaders(),
        body: JSON.stringify({ name: newKeyName.trim() }),
      });
      
      if (res.ok) {
        const data = await res.json();
        if (data.success && data.key) {
          setRevealedKey(data.key);
          setShowCreateModal(false);
          setShowRevealModal(true);
          setNewKeyName('');
          fetchKeys();
        }
      }
    } catch (error) {
      console.error('Failed to create key:', error);
    } finally {
      setActionLoading(null);
    }
  }

  async function revokeKey(keyId: string) {
    if (!confirm('Are you sure you want to revoke this key? It will no longer work for authentication.')) {
      return;
    }
    
    setActionLoading(keyId);
    try {
      const res = await fetch(`${API_URL}/v1/keys/${keyId}/revoke`, {
        method: 'POST',
        headers: await getAuthHeaders(),
      });
      
      if (res.ok) {
        fetchKeys();
      }
    } catch (error) {
      console.error('Failed to revoke key:', error);
    } finally {
      setActionLoading(null);
    }
  }

  async function deleteKey(keyId: string) {
    if (!confirm('Permanently delete this key? This action cannot be undone.')) {
      return;
    }
    
    setActionLoading(keyId);
    try {
      const res = await fetch(`${API_URL}/v1/keys/${keyId}`, {
        method: 'DELETE',
        headers: await getAuthHeaders(),
      });
      
      if (res.ok) {
        fetchKeys();
      }
    } catch (error) {
      console.error('Failed to delete key:', error);
    } finally {
      setActionLoading(null);
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const activeKeys = keys.filter(k => !k.is_revoked);
  const revokedKeys = keys.filter(k => k.is_revoked);

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium lowercase mb-1">api keys & tokens</h1>
          <p className="text-sm text-[#555] lowercase">manage programmatic access and github integration</p>
        </div>
        <div className="flex items-center gap-3">
          <Link 
            href="/docs" 
            className="flex items-center gap-2 px-3 py-2 text-xs text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
          >
            <ExternalLink size={12} />
            docs
          </Link>
          <button 
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
          >
            <Plus size={14} />
            create key
          </button>
        </div>
      </div>

      {/* Keys List */}
      <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] overflow-hidden">
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#333] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#444] lowercase">loading keys...</p>
          </div>
        ) : keys.length === 0 ? (
          <div className="p-12 text-center">
            <Key size={32} className="text-[#222] mx-auto mb-3" />
            <h3 className="text-sm text-[#555] lowercase mb-1">no api keys yet</h3>
            <p className="text-xs text-[#333] lowercase mb-4">create an api key to authenticate your mcp requests.</p>
            <button 
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
            >
              create your first key
            </button>
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {/* Active Keys */}
            {activeKeys.map((key) => (
              <div 
                key={key.id} 
                className="flex items-center gap-4 px-4 py-4 hover:bg-[#111] transition-colors"
              >
                <div className="w-10 h-10 rounded-lg bg-[#fa7315]/10 flex items-center justify-center">
                  <Key size={18} className="text-[#fa7315]" />
                </div>
                
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-white">{key.name}</span>
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider bg-green-500/20 text-green-400">
                      active
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#444]">
                    <code className="font-mono">{key.key_preview}••••••••••••••••</code>
                    <span>•</span>
                    <span>created {formatTimeAgo(key.created_at)}</span>
                    <span>•</span>
                    <span>last used: {formatDate(key.last_used_at)}</span>
                  </div>
                </div>
                
                <div className="flex items-center gap-1">
                  <button 
                    onClick={() => revokeKey(key.id)}
                    disabled={actionLoading === key.id}
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-yellow-500 transition-colors disabled:opacity-50"
                    title="Revoke key"
                  >
                    <Ban size={14} />
                  </button>
                  <button 
                    onClick={() => deleteKey(key.id)}
                    disabled={actionLoading === key.id}
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-red-500 transition-colors disabled:opacity-50"
                    title="Delete key"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}

            {/* Revoked Keys */}
            {revokedKeys.map((key) => (
              <div 
                key={key.id} 
                className="flex items-center gap-4 px-4 py-4 opacity-50"
              >
                <div className="w-10 h-10 rounded-lg bg-[#333]/20 flex items-center justify-center">
                  <Key size={18} className="text-[#444]" />
                </div>
                
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-[#666]">{key.name}</span>
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider bg-red-500/20 text-red-400">
                      revoked
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#333]">
                    <code className="font-mono">{key.key_preview}••••••••••••••••</code>
                    <span>•</span>
                    <span>created {formatTimeAgo(key.created_at)}</span>
                  </div>
                </div>
                
                <button 
                  onClick={() => deleteKey(key.id)}
                  disabled={actionLoading === key.id}
                  className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#333] hover:text-red-500 transition-colors disabled:opacity-50"
                  title="Delete key permanently"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Connect Accounts ─────────────────────────────────────── */}

      {/* Token messages */}
      {(tokenSuccess || hfTokenSuccess) && (
        <div className="mt-6 p-3 rounded-lg bg-green-500/10 border border-green-500/20 text-sm text-green-400 lowercase flex items-center gap-2">
          <Check size={14} />
          {tokenSuccess || hfTokenSuccess}
        </div>
      )}
      {tokenError && !showTokenModal && (
        <div className="mt-6 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400 lowercase">
          {tokenError}
        </div>
      )}
      {hfTokenError && !showHfTokenModal && (
        <div className="mt-6 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400 lowercase">
          {hfTokenError}
        </div>
      )}

      <div id="github-token" className="mt-6 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1a1a1a]">
          <h2 className="text-xs text-[#555] font-medium uppercase tracking-wider">connect accounts</h2>
        </div>

        <div className="divide-y divide-[#1a1a1a]">
          {/* GitHub row */}
          <div className="flex items-center gap-4 px-4 py-4">
            <div className="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center">
              <Github size={20} className="text-white" />
            </div>

            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium text-white">github</span>
              {hasToken && tokenInfo?.github_username && (
                <p className="text-xs text-[#444] mt-0.5">@{tokenInfo.github_username}</p>
              )}
            </div>

            {tokenLoading ? (
              <RefreshCw size={14} className="text-[#333] animate-spin" />
            ) : hasToken ? (
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 text-xs text-green-400">
                  <Check size={14} />
                  connected
                </span>
                <button
                  onClick={deleteToken}
                  className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#333] hover:text-red-500 transition-colors"
                  title="Disconnect"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowTokenModal(true)}
                className="px-3.5 py-1.5 text-xs font-medium rounded-lg border border-[#1a1a1a] text-[#888] hover:text-white hover:border-[#333] transition-colors lowercase"
              >
                connect
              </button>
            )}
          </div>

          {/* HuggingFace row */}
          <div className="flex items-center gap-4 px-4 py-4">
            <div className="w-10 h-10 rounded-lg bg-yellow-500/10 flex items-center justify-center">
              <span className="text-lg">&#129303;</span>
            </div>

            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium text-white">hugging face</span>
              {hasHfToken && hfTokenInfo?.hf_username && (
                <p className="text-xs text-[#444] mt-0.5">{hfTokenInfo.hf_username}</p>
              )}
            </div>

            {hfTokenLoading ? (
              <RefreshCw size={14} className="text-[#333] animate-spin" />
            ) : hasHfToken ? (
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 text-xs text-green-400">
                  <Check size={14} />
                  connected
                </span>
                <button
                  onClick={deleteHfToken}
                  className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#333] hover:text-red-500 transition-colors"
                  title="Disconnect"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowHfTokenModal(true)}
                className="px-3.5 py-1.5 text-xs font-medium rounded-lg border border-[#1a1a1a] text-[#888] hover:text-white hover:border-[#333] transition-colors lowercase"
              >
                connect
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Usage Info — MCP Configuration */}
      <UsageConfigSection />

      {/* Create Key Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div 
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowCreateModal(false)}
          />
          <div className="relative w-full max-w-md mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">create api key</h2>
              <button 
                onClick={() => setShowCreateModal(false)}
                className="p-1 rounded hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            </div>
            
            <div className="mb-6">
              <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">key name</label>
              <input
                type="text"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="e.g., development, mcp setup"
                className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
                autoFocus
              />
              <p className="text-[10px] text-[#333] mt-2">a name to help you identify this key</p>
            </div>
            
            <div className="flex justify-end gap-3">
              <button 
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
              >
                cancel
              </button>
              <button 
                onClick={createKey}
                disabled={!newKeyName.trim() || actionLoading === 'create'}
                className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {actionLoading === 'create' ? 'creating...' : 'create key'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Key Reveal Modal */}
      {showRevealModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div 
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowRevealModal(false)}
          />
          <div className="relative w-full max-w-lg mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">api key created</h2>
              <button 
                onClick={() => setShowRevealModal(false)}
                className="p-1 rounded hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            </div>
            
            <div className="p-4 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a] mb-4">
              <code className="block text-sm font-mono text-[#fa7315] break-all select-all">
                {revealedKey}
              </code>
            </div>
            
            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 mb-6">
              <AlertTriangle size={16} className="text-yellow-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-yellow-200/80">
                make sure to copy your api key now. you won&apos;t be able to see it again!
              </p>
            </div>
            
            <div className="flex justify-end gap-3">
              <button 
                onClick={() => copyToClipboard(revealedKey)}
                className="flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {copied ? 'copied!' : 'copy key'}
              </button>
              <button 
                onClick={() => setShowRevealModal(false)}
                className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
              >
                done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add / Update GitHub Token Modal */}
      {showTokenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowTokenModal(false)}
          />
          <div className="relative w-full max-w-md mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">
                {hasToken ? "update github token" : "connect github"}
              </h2>
              <button
                onClick={() => setShowTokenModal(false)}
                className="p-1 rounded hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="mb-4">
              <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                personal access token
              </label>
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="github_pat_••••••••••••••••••••"
                className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors font-mono"
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && saveToken()}
              />
              <p className="text-[10px] text-[#333] mt-2">
                fine-grained token with <span className="text-[#555]">contents:read</span> permission
              </p>
            </div>

            <div className="mb-4">
              <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                label <span className="text-[#333]">(optional)</span>
              </label>
              <input
                type="text"
                value={labelInput}
                onChange={(e) => setLabelInput(e.target.value)}
                placeholder="e.g., personal, work"
                className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
              />
            </div>

            {/* Collapsible PAT creation guide */}
            <details className="mb-4 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] group">
              <summary className="flex items-center gap-2 px-3 py-2.5 text-xs text-[#555] lowercase cursor-pointer hover:text-white transition-colors select-none">
                <ExternalLink size={10} />
                how to create a fine-grained token
              </summary>
              <div className="px-3 pb-3 space-y-2 text-xs text-[#444] lowercase">
                <p>
                  1. go to{" "}
                  <a
                    href="https://github.com/settings/tokens?type=beta"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#fa7315] hover:text-[#ff8c3a] underline"
                  >
                    github token settings
                  </a>
                </p>
                <p>2. click <span className="text-white">&quot;generate new token&quot;</span> &rarr; <span className="text-white">&quot;fine-grained&quot;</span></p>
                <p>3. repository access &rarr; <span className="text-white">&quot;only select repositories&quot;</span></p>
                <p>4. permissions &rarr; contents &rarr; <span className="text-[#fa7315]">read-only</span></p>
                <p>5. generate &amp; paste above</p>
              </div>
            </details>

            <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.03] border border-[#1a1a1a] mb-6">
              <Lock size={14} className="text-[#444] flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-[#444] lowercase">
                encrypted (aes) before storage. decrypted only in-memory at clone time. never logged or exposed.
              </p>
            </div>

            {tokenError && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400 lowercase">
                {tokenError}
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowTokenModal(false); setTokenError(null); }}
                className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
              >
                cancel
              </button>
              <button
                onClick={saveToken}
                disabled={!tokenInput.trim() || tokenSaving}
                className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {tokenSaving ? "validating..." : "connect"}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Add / Update HuggingFace Token Modal */}
      {showHfTokenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowHfTokenModal(false)}
          />
          <div className="relative w-full max-w-md mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">
                {hasHfToken ? "update hugging face token" : "connect hugging face"}
              </h2>
              <button
                onClick={() => setShowHfTokenModal(false)}
                className="p-1 rounded hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="mb-4">
              <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                access token
              </label>
              <input
                type="password"
                value={hfTokenInput}
                onChange={(e) => setHfTokenInput(e.target.value)}
                placeholder="hf_••••••••••••••••••••"
                className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors font-mono"
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && saveHfToken()}
              />
              <p className="text-[10px] text-[#333] mt-2">
                token with <span className="text-[#555]">read</span> access to datasets
              </p>
            </div>

            <div className="mb-4">
              <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                label <span className="text-[#333]">(optional)</span>
              </label>
              <input
                type="text"
                value={hfLabelInput}
                onChange={(e) => setHfLabelInput(e.target.value)}
                placeholder="e.g., personal, work"
                className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
              />
            </div>

            {/* Token creation guide */}
            <details className="mb-4 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] group">
              <summary className="flex items-center gap-2 px-3 py-2.5 text-xs text-[#555] lowercase cursor-pointer hover:text-white transition-colors select-none">
                <ExternalLink size={10} />
                how to create an access token
              </summary>
              <div className="px-3 pb-3 space-y-2 text-xs text-[#444] lowercase">
                <p>
                  1. go to{" "}
                  <a
                    href="https://huggingface.co/settings/tokens"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#fa7315] hover:text-[#ff8c3a] underline"
                  >
                    huggingface token settings
                  </a>
                </p>
                <p>2. click <span className="text-white">&quot;create new token&quot;</span></p>
                <p>3. select <span className="text-[#fa7315]">read</span> access</p>
                <p>4. generate &amp; paste above</p>
              </div>
            </details>

            <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.03] border border-[#1a1a1a] mb-6">
              <Lock size={14} className="text-[#444] flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-[#444] lowercase">
                encrypted (aes) before storage. decrypted only in-memory during indexing. never logged or exposed.
              </p>
            </div>

            {hfTokenError && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400 lowercase">
                {hfTokenError}
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowHfTokenModal(false); setHfTokenError(null); }}
                className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
              >
                cancel
              </button>
              <button
                onClick={saveHfToken}
                disabled={!hfTokenInput.trim() || hfTokenSaving}
                className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {hfTokenSaving ? "validating..." : "connect"}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
