"use client";

import { useState, useEffect, useRef } from "react";
import PageShell from "@/components/PageShell";
import {
  Search, GitBranch, Plus, Trash2, RefreshCw, X,
  FolderGit2, FileCode, Box, Minimize2, Maximize2,
  Lock, Globe, Info, ChevronDown, Check,
} from "lucide-react";
import Link from "next/link";
import { getAuthHeaders, getAccessToken, API_URL, DIRECT_API_URL } from "@/lib/api";

interface Repository {
  repo_id: string;
  owner: string;
  name: string;
  branch: string;
  files_count?: number;
  chunks_count?: number;
  symbols_count?: number;
  created_at?: string;
}

interface GitHubRepo {
  full_name: string;
  name: string;
  owner: string;
  private: boolean;
  default_branch: string;
  description: string;
  updated_at: string | null;
  language: string | null;
  stargazers_count: number;
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

interface IndexingJob {
  id: string;
  repoUrl: string;
  branch: string;
  progress: IndexProgress | null;
  isMinimized: boolean;
  error: string | null;
  success: string | null;
  isIndexing: boolean;
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
  complete: "complete!",
  error: "error",
};

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showIndexModal, setShowIndexModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [deepIndex, setDeepIndex] = useState(false);
  const [actionLoading] = useState<string | null>(null);

  // Track multiple concurrent indexing jobs
  const [indexingJobs, setIndexingJobs] = useState<Map<string, IndexingJob>>(new Map());
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // GitHub repo picker state
  const [hasToken, setHasToken] = useState(false);
  const [ghRepos, setGhRepos] = useState<GitHubRepo[]>([]);
  const [ghSearch, setGhSearch] = useState("");
  const [ghLoading, setGhLoading] = useState(false);
  const [manualMode, setManualMode] = useState(false);

  // Branch picker state
  const [branches, setBranches] = useState<string[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false);
  const [defaultBranch, setDefaultBranch] = useState("main");
  const branchDropdownRef = useRef<HTMLDivElement>(null);

  // Get active job
  const activeJob = activeJobId ? indexingJobs.get(activeJobId) : null;

  // Get minimized jobs
  const minimizedJobs = Array.from(indexingJobs.values()).filter(job => job.isMinimized && job.isIndexing);

  // Fetch repositories
  useEffect(() => {
    fetchRepos();
  }, []);

  async function fetchRepos() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/repositories`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setRepos(data.repositories || []);
      }
    } catch (error) {
      console.error("Failed to fetch repositories:", error);
    } finally {
      setLoading(false);
    }
  }

  // Check if user has a GitHub token stored
  async function checkGitHubToken() {
    try {
      const res = await fetch(`${API_URL}/v1/github/token`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setHasToken(data.has_token ?? false);
        return data.has_token ?? false;
      }
    } catch {
      // ignore
    }
    return false;
  }

  // Fetch GitHub repos accessible via stored PAT
  async function fetchGitHubRepos(query?: string) {
    setGhLoading(true);
    try {
      const params = new URLSearchParams({ per_page: "50" });
      if (query) params.set("q", query);
      const res = await fetch(`${API_URL}/v1/github/repos?${params}`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setGhRepos(data.repos || []);
      }
    } catch {
      // ignore
    } finally {
      setGhLoading(false);
    }
  }

  // Parse owner/name from a GitHub URL or shorthand
  function parseRepo(url: string): { owner: string; name: string } | null {
    // Match "owner/name" or "https://github.com/owner/name[/...]"
    const m = url.trim().match(/(?:github\.com\/)?([^/\s]+)\/([^/\s#?]+)/);
    if (!m) return null;
    return { owner: m[1], name: m[2].replace(/\.git$/, "") };
  }

  // Fetch branches for a given owner/name
  async function fetchBranches(owner: string, name: string) {
    setBranchesLoading(true);
    try {
      const params = new URLSearchParams({ owner, name });
      const res = await fetch(`${API_URL}/v1/github/branches?${params}`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setBranches(data.branches || []);
        if (data.default_branch) {
          setBranch(data.default_branch);
          setDefaultBranch(data.default_branch);
        }
      } else {
        setBranches([]);
      }
    } catch {
      setBranches([]);
    } finally {
      setBranchesLoading(false);
    }
  }

  // Fetch branches when repo URL changes (debounced)
  useEffect(() => {
    if (!repoUrl) {
      setBranches([]);
      return;
    }
    const parsed = parseRepo(repoUrl);
    if (!parsed) return;
    const t = setTimeout(() => fetchBranches(parsed.owner, parsed.name), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoUrl]);

  // Close branch dropdown on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (branchDropdownRef.current && !branchDropdownRef.current.contains(e.target as Node)) {
        setBranchDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Debounced search for GitHub repos
  useEffect(() => {
    if (!showIndexModal || !hasToken || manualMode) return;
    const t = setTimeout(() => {
      fetchGitHubRepos(ghSearch || undefined);
    }, ghSearch ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ghSearch, showIndexModal, hasToken, manualMode]);

  // When modal opens, check for token
  useEffect(() => {
    if (showIndexModal && !activeJob?.isIndexing) {
      checkGitHubToken();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showIndexModal]);

  // Select a repo from the dropdown
  function selectRepo(repo: GitHubRepo) {
    setRepoUrl(`https://github.com/${repo.full_name}`);
    setBranch(repo.default_branch);
    setGhSearch(repo.full_name);
    setManualMode(true); // close dropdown, show filled form
  }

  // Update a job
  function updateJob(jobId: string, updates: Partial<IndexingJob>) {
    setIndexingJobs((prev) => {
      const newMap = new Map(prev);
      const existing = newMap.get(jobId);
      if (existing) {
        newMap.set(jobId, { ...existing, ...updates });
      }
      return newMap;
    });
  }

  // Remove a job
  function removeJob(jobId: string) {
    setIndexingJobs((prev) => {
      const newMap = new Map(prev);
      newMap.delete(jobId);
      return newMap;
    });
    if (activeJobId === jobId) {
      setActiveJobId(null);
    }
  }

  // Index a repository with SSE streaming progress
  async function indexRepository() {
    if (!repoUrl.trim()) return;

    // Create unique job ID
    const jobId = `${Date.now()}-${repoUrl.trim()}`;
    const newJob: IndexingJob = {
      id: jobId,
      repoUrl: repoUrl.trim(),
      branch: branch.trim() || "main",
      progress: { stage: "starting", message: "Starting indexing...", progress: 0 },
      isMinimized: false,
      error: null,
      success: null,
      isIndexing: true,
    };

    // Add job and set as active
    setIndexingJobs((prev) => new Map(prev).set(jobId, newJob));
    setActiveJobId(jobId);

    try {
      const token = (await getAccessToken()) || "";
      const res = await fetch(`${DIRECT_API_URL}/v1/repositories/index/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ url: newJob.repoUrl, branch: newJob.branch, deep_index: deepIndex }),
      });

      if (!res.ok) {
        throw new Error(`HTTP error: ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          // Flush any remaining buffer (final SSE event may not end with \n)
          if (buffer.trim().startsWith("data: ")) {
            try {
              const data = JSON.parse(buffer.trim().substring(6)) as IndexProgress;
              if (data.stage === "complete" && data.result) {
                const r = data.result;
                const successMsg = `indexed ${r.files_indexed || 0} files, ${r.chunks_created || 0} chunks${r.symbols_extracted ? `, ${r.symbols_extracted} symbols` : ""}`;
                updateJob(jobId, {
                  progress: { stage: "complete", message: "Indexing complete!", progress: 100 },
                  success: successMsg,
                  isIndexing: false,
                  isMinimized: false,
                });
                setShowIndexModal(true);
                setActiveJobId(jobId);
                fetchRepos();
                setTimeout(() => {
                  removeJob(jobId);
                  if (activeJobId === jobId) {
                    setShowIndexModal(false);
                    resetModal();
                  }
                }, 5000);
              }
            } catch { /* ignore */ }
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.substring(6)) as IndexProgress;

              if (data.stage === "complete" && data.result) {
                const r = data.result;
                const successMsg = `indexed ${r.files_indexed || 0} files, ${r.chunks_created || 0} chunks${r.symbols_extracted ? `, ${r.symbols_extracted} symbols` : ""}`;

                updateJob(jobId, {
                  progress: { stage: "complete", message: "Indexing complete!", progress: 100 },
                  success: successMsg,
                  isIndexing: false,
                  isMinimized: false,
                });

                setShowIndexModal(true);
                setActiveJobId(jobId);
                fetchRepos();

                setTimeout(() => {
                  removeJob(jobId);
                  if (activeJobId === jobId) {
                    setShowIndexModal(false);
                    resetModal();
                  }
                }, 5000);
                return;
              }

              if (data.stage === "error") {
                updateJob(jobId, {
                  error: data.message || "Indexing failed",
                  isIndexing: false,
                });
                return;
              }

              if (data.stage !== "heartbeat") {
                updateJob(jobId, { progress: data });
              }
            } catch {
              // skip unparseable lines
            }
          }
        }
      }
    } catch (err) {
      updateJob(jobId, {
        error: err instanceof Error ? err.message : "Failed to index repository",
        isIndexing: false,
      });
    }
  }

  // Delete a repository
  async function deleteRepo(repoId: string) {
    if (!confirm("Are you sure you want to delete this repository?")) return;

    // Optimistic removal — hide it from the list immediately
    const previous = repos;
    setRepos((prev) => prev.filter((r) => r.repo_id !== repoId));

    try {
      const res = await fetch(`${API_URL}/v1/repositories/${repoId}`, {
        method: "DELETE",
        headers: await getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        // Restore if the server rejected the delete
        console.error("Delete failed:", data.error || data.message);
        setRepos(previous);
      } else {
        // Re-fetch to sync counts / state
        await fetchRepos();
      }
    } catch (error) {
      console.error("Failed to delete repository:", error);
      setRepos(previous); // Restore on network error
    }
  }

  function resetModal() {
    setRepoUrl("");
    setBranch("main");
    setBranches([]);
    setDeepIndex(false);
    setManualMode(false);
    setGhSearch("");
    setGhRepos([]);
  }

  function minimizeJob(jobId: string) {
    updateJob(jobId, { isMinimized: true });
    setShowIndexModal(false);
    if (activeJobId === jobId) {
      setActiveJobId(null);
    }
  }

  function expandJob(jobId: string) {
    updateJob(jobId, { isMinimized: false });
    setActiveJobId(jobId);
    setShowIndexModal(true);
  }

  // Filter repos by search
  const filtered = repos.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      `${r.owner}/${r.name}`.toLowerCase().includes(q) ||
      r.branch.toLowerCase().includes(q)
    );
  });

  // Stats
  const totalFiles = repos.reduce((s, r) => s + (r.files_count || 0), 0);
  const totalChunks = repos.reduce((s, r) => s + (r.chunks_count || 0), 0);

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium lowercase mb-1">repositories</h1>
          <p className="text-sm text-[#555] lowercase">manage your indexed repositories</p>
        </div>
        <button
          onClick={() => { resetModal(); setShowIndexModal(true); setActiveJobId(null); }}
          className="flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
        >
          <Plus size={14} />
          index new
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <p className="text-[11px] text-[#666] uppercase tracking-wider mb-1">repositories</p>
          <p className="text-2xl font-semibold tabular-nums">{repos.length}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <p className="text-[11px] text-[#666] uppercase tracking-wider mb-1">files</p>
          <p className="text-2xl font-semibold tabular-nums">{totalFiles.toLocaleString()}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <p className="text-[11px] text-[#666] uppercase tracking-wider mb-1">chunks</p>
          <p className="text-2xl font-semibold tabular-nums">{totalChunks.toLocaleString()}</p>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="search repositories..."
            className="w-full h-9 pl-9 pr-4 rounded-lg bg-[#0f0f0f] border border-[#1a1a1a] text-sm text-white placeholder-[#444] focus:outline-none focus:border-[#222] lowercase transition-colors"
          />
        </div>
      </div>

      {/* Repository List */}
      <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] overflow-hidden">
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#333] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#444] lowercase">loading repositories...</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center">
            <FolderGit2 size={32} className="text-[#222] mx-auto mb-3" />
            <h3 className="text-sm text-[#555] lowercase mb-1">
              {repos.length === 0 ? "no repositories yet" : "no matching repositories"}
            </h3>
            <p className="text-xs text-[#333] lowercase mb-4">
              {repos.length === 0
                ? "index your first repository to get started with semantic code search."
                : "try a different search term."}
            </p>
            {repos.length === 0 && (
              <button
                onClick={() => { resetModal(); setShowIndexModal(true); setActiveJobId(null); }}
                className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
              >
                index your first repo
              </button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {filtered.map((repo) => (
              <div
                key={repo.repo_id}
                className="flex items-center gap-4 px-4 py-4 hover:bg-[#111] transition-colors group"
              >
                {/* Icon */}
                <div className="w-10 h-10 rounded-lg bg-[#fa7315]/10 flex items-center justify-center flex-shrink-0">
                  <GitBranch size={18} className="text-[#fa7315]" />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white truncate mb-1">
                    {repo.owner}/{repo.name}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#444]">
                    <span className="flex items-center gap-1">
                      <GitBranch size={10} />
                      {repo.branch}
                    </span>
                    {(repo.files_count ?? 0) > 0 && (
                      <span className="flex items-center gap-1">
                        <FileCode size={10} />
                        {repo.files_count} files
                      </span>
                    )}
                    {(repo.chunks_count ?? 0) > 0 && (
                      <span className="flex items-center gap-1">
                        <Box size={10} />
                        {repo.chunks_count} chunks
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => deleteRepo(repo.repo_id)}
                    disabled={actionLoading === repo.repo_id}
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-red-500 transition-colors disabled:opacity-50"
                    title="Delete repository"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Minimized Indexing Indicators — floating pills at bottom-right */}
      {minimizedJobs.length > 0 && (
        <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-xs">
          {minimizedJobs.map((job) => (
            <button
              key={job.id}
              onClick={() => expandJob(job.id)}
              className="flex items-center gap-3 pl-4 pr-3 py-3 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl shadow-black/40 hover:border-[#2a2a2a] transition-all group cursor-pointer"
            >
              {/* Animated spinner */}
              <RefreshCw size={16} className="text-[#fa7315] animate-spin flex-shrink-0" />

              {/* Info */}
              <div className="flex-1 min-w-0 text-left">
                <p className="text-xs font-medium text-white truncate lowercase">
                  {job.progress && (stageLabels[job.progress.stage] || job.progress.stage)}
                </p>
                <p className="text-[10px] text-[#444] truncate lowercase">
                  {job.repoUrl.replace(/https?:\/\/(www\.)?github\.com\//, "")}
                </p>
              </div>

              {/* Mini progress ring */}
              <div className="relative w-9 h-9 flex-shrink-0">
                <svg className="w-9 h-9 -rotate-90" viewBox="0 0 36 36">
                  <circle
                    cx="18" cy="18" r="15"
                    fill="none" stroke="#1a1a1a" strokeWidth="3"
                  />
                  <circle
                    cx="18" cy="18" r="15"
                    fill="none" stroke="#fa7315" strokeWidth="3"
                    strokeLinecap="round"
                    strokeDasharray={`${Math.max(0, Math.min(job.progress?.progress || 0, 100)) * 0.9425} 94.25`}
                    className="transition-all duration-500"
                  />
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-[9px] font-semibold text-[#fa7315] tabular-nums">
                  {Math.round(Math.max(0, job.progress?.progress || 0))}%
                </span>
              </div>

              {/* Expand icon */}
              <Maximize2 size={14} className="text-[#333] group-hover:text-[#fa7315] transition-colors flex-shrink-0" />
            </button>
          ))}
        </div>
      )}

      {/* Index Repository Modal */}
      {showIndexModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => {
              if (activeJob?.isIndexing) {
                minimizeJob(activeJob.id);
              } else {
                setShowIndexModal(false);
                resetModal();
              }
            }}
          />
          <div className="relative w-full max-w-lg mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">index repository</h2>
              <div className="flex items-center gap-1">
                {/* Minimize button — visible during indexing */}
                {activeJob?.isIndexing && (
                  <button
                    onClick={() => minimizeJob(activeJob.id)}
                    className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#555] hover:text-[#fa7315] transition-colors"
                    title="Minimize — indexing continues in the background"
                  >
                    <Minimize2 size={15} />
                  </button>
                )}
                {/* Close button — visible when not indexing */}
                {!activeJob?.isIndexing && (
                  <button
                    onClick={() => { setShowIndexModal(false); resetModal(); }}
                    className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
                  >
                    <X size={15} />
                  </button>
                )}
              </div>
            </div>

            {/* PAT info banner — only when user has no token */}
            {!activeJob?.isIndexing && !activeJob?.success && !hasToken && (
              <Link
                href="/api-keys#github-token"
                className="flex items-start gap-2.5 mb-5 p-3 rounded-lg bg-[#fa7315]/8 border border-[#fa7315]/15 hover:border-[#fa7315]/30 transition-colors group"
              >
                <Info size={14} className="text-[#fa7315] mt-0.5 flex-shrink-0" />
                <p className="text-xs text-[#888] lowercase leading-relaxed">
                  index your private repos by adding a github PAT in{" "}
                  <span className="text-[#fa7315] group-hover:underline">api keys</span>
                </p>
              </Link>
            )}

            {/* Form (hidden during indexing) */}
            {!activeJob?.isIndexing && !activeJob?.success && (
              <div>
                {/* GitHub repo dropdown — only when user has a token */}
                {hasToken && (
                  <div className="mb-4">
                    <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                      select private repo
                    </label>
                    <div>
                      <div className="relative">
                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444] z-10" />
                        <input
                          type="text"
                          value={ghSearch}
                          onChange={(e) => { setGhSearch(e.target.value); setManualMode(false); }}
                          onFocus={() => setManualMode(false)}
                          placeholder="search your github repos..."
                          className="w-full h-10 pl-9 pr-4 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors lowercase"
                        />
                      </div>
                      {/* Repo list — inline, expands the modal */}
                      {!manualMode && (
                        <div className="mt-1 max-h-48 overflow-y-auto rounded-lg bg-[#0a0a0a] border border-[#1a1a1a]">
                          {ghLoading ? (
                            <div className="p-4 text-center">
                              <RefreshCw size={14} className="text-[#333] animate-spin mx-auto mb-1" />
                              <p className="text-[10px] text-[#444] lowercase">loading...</p>
                            </div>
                          ) : ghRepos.length === 0 ? (
                            <div className="p-4 text-center">
                              <p className="text-xs text-[#333] lowercase">
                                {ghSearch ? "no matching repos" : "no repos found"}
                              </p>
                            </div>
                          ) : (
                            ghRepos.map((repo) => (
                              <button
                                key={repo.full_name}
                                onClick={() => selectRepo(repo)}
                                className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-[#151515] transition-colors text-left"
                              >
                                <span className="text-[#333] flex-shrink-0">
                                  {repo.private ? <Lock size={12} /> : <Globe size={12} />}
                                </span>
                                <span className="text-sm text-white truncate flex-1">{repo.full_name}</span>
                                {repo.private && (
                                  <span className="px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase tracking-wider bg-yellow-500/15 text-yellow-500 flex-shrink-0">
                                    private
                                  </span>
                                )}
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* OR divider — only when user has a token */}
                {hasToken && (
                  <div className="flex items-center gap-3 my-4">
                    <div className="flex-1 h-px bg-[#1a1a1a]" />
                    <span className="text-[10px] text-[#333] uppercase tracking-wider">or</span>
                    <div className="flex-1 h-px bg-[#1a1a1a]" />
                  </div>
                )}

                {/* Manual URL input */}
                <div className="mb-4">
                  <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                    {hasToken ? "enter repository url" : "repository url or shorthand"}
                  </label>
                  <input
                    type="text"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    onFocus={() => setManualMode(true)}
                    placeholder="facebook/react or https://github.com/facebook/react"
                    className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
                    autoFocus={!hasToken}
                  />
                </div>

                {/* Branch */}
                <div className="mb-6" ref={branchDropdownRef}>
                  <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                    branch
                  </label>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => !branchesLoading && setBranchDropdownOpen(!branchDropdownOpen)}
                      className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-left flex items-center gap-2 hover:border-[#333] focus:outline-none focus:border-[#333] transition-colors"
                    >
                      <GitBranch size={12} className="text-[#444] flex-shrink-0" />
                      <span className="text-white lowercase truncate flex-1">{branch}</span>
                      {branchesLoading ? (
                        <RefreshCw size={12} className="text-[#444] animate-spin flex-shrink-0" />
                      ) : (
                        <ChevronDown size={12} className={`text-[#444] flex-shrink-0 transition-transform ${branchDropdownOpen ? "rotate-180" : ""}`} />
                      )}
                    </button>

                    {branchDropdownOpen && branches.length > 0 && (
                      <div className="absolute z-50 mt-1 w-full max-h-48 overflow-y-auto rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] shadow-xl shadow-black/50">
                        {branches.map((b) => (
                          <button
                            key={b}
                            type="button"
                            onClick={() => {
                              setBranch(b);
                              setBranchDropdownOpen(false);
                            }}
                            className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition-colors lowercase ${
                              b === branch
                                ? "bg-[#151515] text-white"
                                : "text-[#888] hover:bg-[#111] hover:text-white"
                            }`}
                          >
                            <span className="w-4 flex-shrink-0">
                              {b === branch && <Check size={12} className="text-[#fa7315]" />}
                            </span>
                            <span className="truncate">{b}</span>
                            {b === defaultBranch && (
                              <span className="ml-auto px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase tracking-wider bg-[#1a1a1a] text-[#555] flex-shrink-0">
                                default
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Deep index toggle */}
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <label className="block text-xs text-[#555] uppercase tracking-wider">
                      deep indexing
                    </label>
                    <p className="text-[10px] text-[#333] mt-0.5">
                      full AST chunking per function/class — slower, higher quality
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setDeepIndex(!deepIndex)}
                    className={`relative flex-shrink-0 w-9 h-5 rounded-full transition-colors ${
                      deepIndex ? "bg-[#fa7315]" : "bg-[#1a1a1a] border border-[#333]"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-transform ${
                        deepIndex ? "translate-x-4 bg-black" : "translate-x-0 bg-[#555]"
                      }`}
                    />
                  </button>
                </div>
              </div>
            )}

            {/* Progress */}
            {activeJob?.isIndexing && activeJob.progress && (
              <div className="mb-6">
                <div className="text-center mb-4">
                  <RefreshCw size={24} className="text-[#fa7315] animate-spin mx-auto mb-3" />
                  <p className="text-sm font-medium text-white lowercase mb-1">
                    {stageLabels[activeJob.progress.stage] || activeJob.progress.stage}
                  </p>
                  <p className="text-xs text-[#555] lowercase">{activeJob.progress.message}</p>
                </div>

                {/* Progress bar */}
                <div className="h-2 bg-[#1a1a1a] rounded-full overflow-hidden mb-2">
                  <div
                    className="h-full bg-[#fa7315] rounded-full transition-all duration-300"
                    style={{ width: `${Math.max(0, Math.min(activeJob.progress.progress, 100))}%` }}
                  />
                </div>
                <p className="text-[10px] text-[#333] text-center tabular-nums">
                  {Math.round(Math.max(0, activeJob.progress.progress))}%
                </p>

                {/* File/chunk details */}
                {(activeJob.progress.total_files || activeJob.progress.chunks_created) && (
                  <div className="mt-4 p-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-xs text-[#444] space-y-1">
                    {activeJob.progress.total_files && (
                      <p>files: {activeJob.progress.files_processed || 0}/{activeJob.progress.total_files}</p>
                    )}
                    {activeJob.progress.chunks_created && (
                      <p>chunks: {activeJob.progress.chunks_created}</p>
                    )}
                  </div>
                )}

                {/* Minimize hint */}
                <p className="mt-4 text-[10px] text-[#333] text-center lowercase">
                  tip: click minimize or the backdrop to continue browsing while indexing
                </p>
              </div>
            )}

            {/* Success message */}
            {activeJob?.success && (
              <div className="mb-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 text-sm text-green-400 lowercase">
                {activeJob.success}
              </div>
            )}

            {/* Error message */}
            {activeJob?.error && (
              <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400 lowercase">
                {activeJob.error}
              </div>
            )}

            {/* Footer buttons */}
            {!activeJob?.isIndexing && !activeJob?.success && (
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => { setShowIndexModal(false); resetModal(); }}
                  className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
                >
                  cancel
                </button>
                <button
                  onClick={indexRepository}
                  disabled={!repoUrl.trim()}
                  className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  index repository
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
