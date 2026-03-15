"use client";

import PageShell from "@/components/PageShell";
import { useState, useEffect } from "react";
import {
  Database, Plus, Search, X, Trash2, ExternalLink,
  RefreshCw, Minimize2, Maximize2, Key,
} from "lucide-react";
import Link from "next/link";
import { getAuthHeaders, API_URL, DIRECT_API_URL } from "@/lib/api";

interface Dataset {
  dataset_id: string;
  hf_id: string;
  owner?: string;
  name: string;
  description?: string;
  license?: string;
  downloads?: number;
  likes?: number;
  languages?: string[];
  tags?: string[];
  chunk_count?: number;
  indexed_at?: string;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [hfInput, setHfInput] = useState("");
  const [isIndexing, setIsIndexing] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [indexSuccess, setIndexSuccess] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // HF token state
  const [hasHfToken, setHasHfToken] = useState<boolean | null>(null);
  const [hfTokenLoading, setHfTokenLoading] = useState(true);

  useEffect(() => {
    checkHfToken();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function checkHfToken() {
    setHfTokenLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/huggingface/token`, {
        headers: await getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setHasHfToken(data.has_token ?? false);
        if (data.has_token) {
          fetchDatasets();
        } else {
          setLoading(false);
        }
      } else {
        setHasHfToken(false);
        setLoading(false);
      }
    } catch {
      setHasHfToken(false);
      setLoading(false);
    } finally {
      setHfTokenLoading(false);
    }
  }

  async function fetchDatasets() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/datasets`, { headers: await getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
      }
    } catch (error) {
      console.error("Failed to fetch datasets:", error);
    } finally {
      setLoading(false);
    }
  }

  async function indexDataset() {
    if (!hfInput.trim()) return;

    setIsIndexing(true);
    setIndexError(null);
    setIndexSuccess(null);
    try {
      const res = await fetch(`${DIRECT_API_URL}/v1/datasets/index`, {
        method: "POST",
        headers: await getAuthHeaders(),
        body: JSON.stringify({ hf_id: hfInput.trim() }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setIndexSuccess(
            `indexed "${data.name || data.hf_id}" — ${data.chunks || 0} chunks`
          );
          setIsIndexing(false);
          setIsMinimized(false);
          setShowAddModal(true);
          fetchDatasets();
          setTimeout(() => {
            setShowAddModal(false);
            resetModal();
          }, 2000);
        } else {
          setIndexError(data.error || "Unknown error");
          setIsIndexing(false);
        }
      } else {
        const error = await res.json();
        setIndexError(error.detail || error.error || "Unknown error");
        setIsIndexing(false);
      }
    } catch (error) {
      console.error("Failed to index dataset:", error);
      setIndexError("Failed to index dataset. Please try again.");
      setIsIndexing(false);
    }
  }

  async function removeDataset(datasetId: string) {
    if (!confirm("Remove this dataset from your collection?")) return;

    setActionLoading(datasetId);
    try {
      const res = await fetch(`${API_URL}/v1/datasets/${datasetId}`, {
        method: "DELETE",
        headers: await getAuthHeaders(),
      });

      if (res.ok) {
        fetchDatasets();
      }
    } catch (error) {
      console.error("Failed to remove dataset:", error);
    } finally {
      setActionLoading(null);
    }
  }

  function resetModal() {
    setHfInput("");
    setIndexError(null);
    setIndexSuccess(null);
    setIsIndexing(false);
    setIsMinimized(false);
  }

  const filteredDatasets = datasets.filter((d) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      d.name?.toLowerCase().includes(q) ||
      d.hf_id?.toLowerCase().includes(q) ||
      d.description?.toLowerCase().includes(q) ||
      d.tags?.some((t) => t.toLowerCase().includes(q))
    );
  });

  // Show loading while checking HF token
  if (hfTokenLoading) {
    return (
      <PageShell>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-medium lowercase mb-1">datasets</h1>
            <p className="text-sm text-[#555] lowercase">huggingface datasets indexed via api & mcp</p>
          </div>
        </div>
        <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] p-12 text-center">
          <RefreshCw size={24} className="text-[#333] animate-spin mx-auto mb-3" />
          <p className="text-sm text-[#444] lowercase">loading...</p>
        </div>
      </PageShell>
    );
  }

  // Show connect HuggingFace CTA if no token
  if (hasHfToken === false) {
    return (
      <PageShell>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-medium lowercase mb-1">datasets</h1>
            <p className="text-sm text-[#555] lowercase">huggingface datasets indexed via api & mcp</p>
          </div>
        </div>
        <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] p-12 text-center">
          <Key size={32} className="text-[#222] mx-auto mb-3" />
          <h3 className="text-sm text-[#555] lowercase mb-1">hugging face token required</h3>
          <p className="text-xs text-[#333] lowercase mb-4 max-w-md mx-auto">
            connect your hugging face account to index and search datasets.
            your token is encrypted and used only for dataset api calls.
          </p>
          <Link
            href="/api-keys#github-token"
            className="inline-flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
          >
            <Key size={14} />
            connect hugging face
          </Link>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium lowercase mb-1">datasets</h1>
          <p className="text-sm text-[#555] lowercase">huggingface datasets indexed via api & mcp</p>
        </div>
        <button
          onClick={() => { resetModal(); setShowAddModal(true); }}
          className="flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
        >
          <Plus size={14} />
          add dataset
        </button>
      </div>

      {/* Card Container */}
      <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#1a1a1a]">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="search datasets..."
              className="w-full h-9 pl-9 pr-4 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#444] focus:outline-none focus:border-[#333] lowercase transition-colors"
            />
          </div>
        </div>

        {/* Datasets List */}
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#333] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#444] lowercase">loading datasets...</p>
          </div>
        ) : filteredDatasets.length === 0 ? (
          <div className="p-12 text-center">
            <Database size={32} className="text-[#222] mx-auto mb-3" />
            <h3 className="text-sm text-[#555] lowercase mb-1">no datasets yet</h3>
            <p className="text-xs text-[#333] lowercase mb-4">
              add huggingface datasets to search their documentation with ai agents.
            </p>
            <button
              onClick={() => { resetModal(); setShowAddModal(true); }}
              className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
            >
              add your first dataset
            </button>
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {filteredDatasets.map((dataset) => (
              <div
                key={dataset.dataset_id}
                className="flex items-center gap-4 px-4 py-4 hover:bg-[#111] transition-colors group"
              >
                {/* Icon */}
                <div className="w-10 h-10 rounded-lg bg-[#fa7315]/10 flex items-center justify-center flex-shrink-0">
                  <Database size={18} className="text-[#fa7315]" />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white truncate mb-1">
                    {dataset.hf_id}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#444]">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium uppercase bg-yellow-500/20 text-yellow-500">
                      HF
                    </span>
                    {dataset.license && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#1a1a1a] text-[#666]">
                        {dataset.license}
                      </span>
                    )}
                    {dataset.downloads != null && dataset.downloads > 0 && (
                      <span>{formatDownloads(dataset.downloads)} downloads</span>
                    )}
                    {dataset.chunk_count != null && dataset.chunk_count > 0 && (
                      <span>{dataset.chunk_count} chunks</span>
                    )}
                    {dataset.languages && dataset.languages.length > 0 && (
                      <span>{dataset.languages.slice(0, 3).join(", ")}</span>
                    )}
                  </div>
                  {dataset.description && (
                    <p className="text-xs text-[#333] mt-1 truncate max-w-[500px]">
                      {dataset.description}
                    </p>
                  )}
                </div>

                {/* Date */}
                <span className="text-xs text-[#333] flex-shrink-0">
                  {dataset.indexed_at ? formatDate(dataset.indexed_at) : "-"}
                </span>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <a
                    href={`https://huggingface.co/datasets/${dataset.hf_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-white transition-colors"
                    title="View on HuggingFace"
                  >
                    <ExternalLink size={14} />
                  </a>
                  <button
                    onClick={() => removeDataset(dataset.dataset_id)}
                    disabled={actionLoading === dataset.dataset_id}
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-red-500 transition-colors disabled:opacity-50"
                    title="Remove dataset"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Minimized Indexing Indicator */}
      {isMinimized && isIndexing && (
        <button
          onClick={() => { setIsMinimized(false); setShowAddModal(true); }}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-3 pl-4 pr-3 py-3 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl shadow-black/40 hover:border-[#2a2a2a] transition-all group cursor-pointer max-w-xs"
        >
          <RefreshCw size={16} className="text-[#fa7315] animate-spin flex-shrink-0" />
          <div className="flex-1 min-w-0 text-left">
            <p className="text-xs font-medium text-white truncate lowercase">indexing dataset...</p>
            <p className="text-[10px] text-[#444] truncate lowercase">{hfInput}</p>
          </div>
          <Maximize2 size={14} className="text-[#333] group-hover:text-[#fa7315] transition-colors flex-shrink-0" />
        </button>
      )}

      {/* Add Dataset Modal */}
      {showAddModal && !isMinimized && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => {
              if (isIndexing) {
                setIsMinimized(true);
                setShowAddModal(false);
              } else {
                setShowAddModal(false);
                resetModal();
              }
            }}
          />
          <div className="relative w-full max-w-lg mx-4 p-6 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium lowercase">add dataset</h2>
              <div className="flex items-center gap-1">
                {isIndexing && (
                  <button
                    onClick={() => { setIsMinimized(true); setShowAddModal(false); }}
                    className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#555] hover:text-[#fa7315] transition-colors"
                    title="Minimize — indexing continues in the background"
                  >
                    <Minimize2 size={15} />
                  </button>
                )}
                {!isIndexing && (
                  <button
                    onClick={() => { setShowAddModal(false); resetModal(); }}
                    className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#555] hover:text-white transition-colors"
                  >
                    <X size={15} />
                  </button>
                )}
              </div>
            </div>

            {/* Form */}
            {!isIndexing && !indexSuccess && (
              <div className="mb-6">
                <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">
                  huggingface dataset id or url
                </label>
                <input
                  type="text"
                  value={hfInput}
                  onChange={(e) => setHfInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") indexDataset(); }}
                  placeholder="e.g., imdb or https://huggingface.co/datasets/openai/gsm8k"
                  className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
                  autoFocus
                />
                <p className="text-[10px] text-[#333] mt-2">
                  paste a dataset id or huggingface url
                </p>
              </div>
            )}

            {/* Indexing progress */}
            {isIndexing && (
              <div className="mb-6">
                <div className="text-center mb-4">
                  <RefreshCw size={24} className="text-[#fa7315] animate-spin mx-auto mb-3" />
                  <p className="text-sm font-medium text-white lowercase mb-1">indexing dataset...</p>
                  <p className="text-xs text-[#555] lowercase">
                    fetching metadata & generating embeddings for {hfInput}
                  </p>
                </div>
                <div className="h-2 bg-[#1a1a1a] rounded-full overflow-hidden mb-2">
                  <div className="h-full bg-[#fa7315] rounded-full animate-pulse" style={{ width: "60%" }} />
                </div>
                <p className="text-[10px] text-[#333] text-center lowercase">
                  this may take 30-60 seconds for embedding generation
                </p>
                <p className="mt-4 text-[10px] text-[#333] text-center lowercase">
                  tip: click minimize or the backdrop to continue browsing while indexing
                </p>
              </div>
            )}

            {/* Success */}
            {indexSuccess && (
              <div className="mb-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 text-sm text-green-400 lowercase">
                {indexSuccess}
              </div>
            )}

            {/* Error */}
            {indexError && !isIndexing && (
              <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400 lowercase">
                {indexError}
              </div>
            )}

            {/* Footer buttons */}
            {!isIndexing && !indexSuccess && (
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => { setShowAddModal(false); resetModal(); }}
                  className="px-4 py-2 text-sm text-[#555] hover:text-white rounded-lg border border-[#1a1a1a] hover:border-[#333] transition-colors lowercase"
                >
                  cancel
                </button>
                <button
                  onClick={indexDataset}
                  disabled={!hfInput.trim()}
                  className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  index dataset
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
