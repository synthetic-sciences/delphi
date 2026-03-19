"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import PageShell from "@/components/PageShell";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useUserProfile } from "@/contexts/UserProfileContext";
import {
  Search, GitBranch, Trash2, RefreshCw, Shield,
  FileCode, Box, Layers, Zap, Globe, Lock,
} from "lucide-react";
import { getAuthHeaders, API_URL, DIRECT_API_URL } from "@/lib/api";

interface AdminRepo {
  repo_id: string;
  owner: string;
  name: string;
  url: string;
  branch: string;
  commit_sha: string | null;
  is_public: boolean;
  indexed_by: string | null;
  files_count: number;
  chunks_count: number;
  symbols_count: number;
  total_lines: number;
  total_tokens: number;
  languages: Record<string, number>;
  deep_indexed: boolean;
  indexed_at: string | null;
  updated_at: string | null;
}

interface IndexProgress {
  stage: string;
  message: string;
  progress: number;
  files_processed?: number;
  total_files?: number;
  chunks_created?: number;
  result?: Record<string, unknown>;
}

const stageLabels: Record<string, string> = {
  starting: "starting",
  parsing: "parsing url",
  checking: "checking repository",
  cloning: "cloning repository",
  cloned: "repository cloned",
  listing: "listing files",
  listed: "files listed",
  indexing: "processing files",
  processing_files: "processing files",
  files_done: "files processed",
  embeddings_start: "generating embeddings",
  generating_embeddings: "generating embeddings",
  embeddings_done: "embeddings ready",
  relationships_built: "building relationships",
  committing: "saving to database",
  reading: "reading files",
  chunking: "chunking files",
  embeddings: "generating embeddings",
  computing_diff: "comparing files",
  removing_deleted: "removing changed files",
  reprocessing: "re-processing changed files",
  relationships: "building relationships",
  complete: "complete!",
  error: "error",
};

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function topLanguage(languages: Record<string, number>): string | null {
  const entries = Object.entries(languages);
  if (entries.length === 0) return null;
  entries.sort((a, b) => b[1] - a[1]);
  return entries[0][0];
}

export default function AdminReposPage() {
  const { profile, loading: profileLoading } = useUserProfile();
  const router = useRouter();

  const [repos, setRepos] = useState<AdminRepo[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Inline progress tracking for reindex/deep-index
  const [activeAction, setActiveAction] = useState<{
    repoId: string;
    type: "reindex" | "deep-index";
    progress: IndexProgress | null;
    error: string | null;
  } | null>(null);

  // Redirect non-admins
  useEffect(() => {
    if (!profileLoading && (!profile || !profile.is_admin)) {
      router.replace("/overview");
    }
  }, [profile, profileLoading, router]);

  useEffect(() => {
    fetchRepos();
  }, []);

  async function fetchRepos() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/admin/repositories`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setRepos(data.repositories || []);
      }
    } catch (error) {
      console.error("Failed to fetch admin repositories:", error);
    } finally {
      setLoading(false);
    }
  }

  async function hardDeleteRepo(repoId: string) {
    const previous = repos;
    setRepos((prev) => prev.filter((r) => r.repo_id !== repoId));

    try {
      const res = await fetch(`${API_URL}/v1/admin/repositories/${repoId}`, {
        method: "DELETE",
        headers: await getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        setRepos(previous);
      } else {
        await fetchRepos();
      }
    } catch {
      setRepos(previous);
    }
  }

  async function reindexRepo(repo: AdminRepo, deepIndex: boolean = false) {
    const actionType = deepIndex ? "deep-index" : "reindex";
    setActiveAction({
      repoId: repo.repo_id,
      type: actionType,
      progress: { stage: "starting", message: "Starting...", progress: 0 },
      error: null,
    });

    try {
      const url = repo.url || `https://github.com/${repo.owner}/${repo.name}`;
      const res = await fetch(`${DIRECT_API_URL}/v1/repositories/index/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          url,
          branch: repo.branch,
          deep_index: deepIndex,
          force_reindex: deepIndex,
        }),
      });

      if (!res.ok) throw new Error(`HTTP error: ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.substring(6)) as IndexProgress;
            if (data.stage === "complete") {
              setActiveAction(null);
              fetchRepos();
              return;
            }
            if (data.stage === "error") {
              setActiveAction((prev) =>
                prev ? { ...prev, error: data.message || "Failed", progress: null } : null
              );
              return;
            }
            if (data.stage !== "heartbeat") {
              setActiveAction((prev) =>
                prev ? { ...prev, progress: data } : null
              );
            }
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      setActiveAction((prev) =>
        prev
          ? { ...prev, error: err instanceof Error ? err.message : "Failed", progress: null }
          : null
      );
    }
  }

  const filtered = repos.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      `${r.owner}/${r.name}`.toLowerCase().includes(q) ||
      r.branch.toLowerCase().includes(q) ||
      (topLanguage(r.languages) || "").toLowerCase().includes(q)
    );
  });

  const totalFiles = repos.reduce((s, r) => s + r.files_count, 0);
  const totalChunks = repos.reduce((s, r) => s + r.chunks_count, 0);
  const deepCount = repos.filter((r) => r.deep_indexed).length;

  // Don't render until we confirm admin status
  if (profileLoading || !profile?.is_admin) {
    return (
      <PageShell>
        <div className="p-12 text-center">
          <RefreshCw size={24} className="text-[#a09488] animate-spin mx-auto mb-3" />
          <p className="text-sm text-[#a09488] lowercase">loading...</p>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#b58a73]/10 flex items-center justify-center">
            <Shield size={18} className="text-[#b58a73]" />
          </div>
          <div>
            <h1 className="text-2xl font-medium lowercase mb-1">admin / repositories</h1>
            <p className="text-sm text-[#8a7a72] lowercase">
              all indexed repositories — hard delete, reindex, deep index
            </p>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">repositories</p>
          <p className="text-2xl font-semibold tabular-nums">{repos.length}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">files</p>
          <p className="text-2xl font-semibold tabular-nums">{formatNumber(totalFiles)}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">chunks</p>
          <p className="text-2xl font-semibold tabular-nums">{formatNumber(totalChunks)}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">deep indexed</p>
          <p className="text-2xl font-semibold tabular-nums">
            {deepCount}<span className="text-sm text-[#a09488] font-normal">/{repos.length}</span>
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#a09488]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="search repositories..."
            className="w-full h-9 pl-9 pr-4 rounded-lg bg-[#faf5ef] border border-[#dfcdbf] text-sm text-[#2e2522] placeholder-[#a09488] focus:outline-none focus:border-[#c5b5a5] lowercase transition-colors"
          />
        </div>
      </div>

      {/* Repository List */}
      <div className="rounded-xl bg-[#faf5ef] border border-[#dfcdbf] overflow-hidden">
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#a09488] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#a09488] lowercase">loading repositories...</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center">
            <Shield size={32} className="text-[#222] mx-auto mb-3" />
            <h3 className="text-sm text-[#8a7a72] lowercase mb-1">
              {repos.length === 0 ? "no repositories indexed" : "no matching repositories"}
            </h3>
          </div>
        ) : (
          <div className="divide-y divide-[#dfcdbf]">
            {filtered.map((repo) => {
              const isActive = activeAction?.repoId === repo.repo_id;
              const lang = topLanguage(repo.languages);

              return (
                <div key={repo.repo_id}>
                  <div className="flex items-center gap-4 px-4 py-4 hover:bg-[#efe7dd] transition-colors group">
                    {/* Icon */}
                    <div className="w-10 h-10 rounded-lg bg-[#b58a73]/10 flex items-center justify-center flex-shrink-0">
                      <GitBranch size={18} className="text-[#b58a73]" />
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-[#2e2522] truncate">
                          {repo.owner}/{repo.name}
                        </span>
                        {repo.is_public ? (
                          <Globe size={12} className="text-[#a09488] flex-shrink-0" />
                        ) : (
                          <Lock size={12} className="text-[#a09488] flex-shrink-0" />
                        )}
                        {repo.deep_indexed && (
                          <span className="px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase tracking-wider bg-[#b58a73]/15 text-[#b58a73] flex-shrink-0">
                            deep
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-[#a09488]">
                        <span className="flex items-center gap-1">
                          <GitBranch size={10} />
                          {repo.branch}
                        </span>
                        <span className="flex items-center gap-1">
                          <FileCode size={10} />
                          {formatNumber(repo.files_count)} files
                        </span>
                        <span className="flex items-center gap-1">
                          <Box size={10} />
                          {formatNumber(repo.chunks_count)} chunks
                        </span>
                        {repo.symbols_count > 0 && (
                          <span className="flex items-center gap-1">
                            <Layers size={10} />
                            {formatNumber(repo.symbols_count)} symbols
                          </span>
                        )}
                        {lang && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#dfcdbf] text-[#8a7a72]">
                            {lang}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Date */}
                    <span className="text-xs text-[#a09488] flex-shrink-0">
                      {repo.indexed_at ? formatDate(repo.indexed_at) : "-"}
                    </span>

                    {/* Actions */}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {/* Deep index button — only if NOT already deep indexed */}
                      {!repo.deep_indexed && (
                        <button
                          onClick={() => reindexRepo(repo, true)}
                          disabled={isActive}
                          className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-[#b58a73] hover:bg-[#b58a73]/10 transition-colors disabled:opacity-50"
                          title="Deep index — full AST chunking per function/class"
                        >
                          <Zap size={12} />
                          <span className="lowercase">deep index</span>
                        </button>
                      )}
                      {/* Update index */}
                      <button
                        onClick={() => reindexRepo(repo, false)}
                        disabled={isActive}
                        className="p-2 rounded-lg hover:bg-[#dfcdbf] text-[#a09488] hover:text-[#b58a73] transition-colors disabled:opacity-50"
                        title="Update index — check for latest commits"
                      >
                        <RefreshCw size={14} />
                      </button>
                      {/* Hard delete */}
                      <button
                        onClick={() => setConfirmDelete(repo.repo_id)}
                        disabled={isActive}
                        className="p-2 rounded-lg hover:bg-[#dfcdbf] text-[#a09488] hover:text-red-500 transition-colors disabled:opacity-50"
                        title="Permanently delete repository and all data"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>

                  {/* Inline progress bar */}
                  {isActive && activeAction.progress && (
                    <div className="px-4 pb-4 -mt-1">
                      <div className="flex items-center gap-3">
                        <RefreshCw size={12} className="text-[#b58a73] animate-spin flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-[#8a7a72] lowercase">
                              {activeAction.type === "deep-index" ? "deep indexing" : "updating"} — {stageLabels[activeAction.progress.stage] || activeAction.progress.stage}
                            </span>
                            <span className="text-[10px] text-[#a09488] tabular-nums">
                              {Math.round(activeAction.progress.progress)}%
                            </span>
                          </div>
                          <div className="h-1 bg-[#dfcdbf] rounded-full overflow-hidden">
                            <div
                              className="h-full bg-[#b58a73] rounded-full transition-all duration-500"
                              style={{ width: `${Math.max(2, Math.min(activeAction.progress.progress, 100))}%` }}
                            />
                          </div>
                        </div>
                        <button
                          onClick={() => setActiveAction(null)}
                          className="text-[10px] text-[#a09488] hover:text-[#2e2522] lowercase"
                        >
                          dismiss
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Inline error */}
                  {isActive && activeAction.error && (
                    <div className="px-4 pb-4 -mt-1">
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-red-500 lowercase flex-1">{activeAction.error}</span>
                        <button
                          onClick={() => setActiveAction(null)}
                          className="text-[10px] text-[#a09488] hover:text-[#2e2522] lowercase"
                        >
                          dismiss
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        title="permanently delete repository?"
        message="this will hard-delete the repository and ALL its data — files, chunks, symbols, and embeddings. this cannot be undone."
        confirmLabel="delete permanently"
        destructive
        onConfirm={() => {
          if (confirmDelete) hardDeleteRepo(confirmDelete);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </PageShell>
  );
}
