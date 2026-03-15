"use client";

import PageShell from "@/components/PageShell";
import { useState, useEffect, useRef } from "react";
import {
  FileText, Plus, Search, X, Trash2, ExternalLink,
  RefreshCw, Upload, Link as LinkIcon, Minimize2, Maximize2
} from "lucide-react";
import { getAuthHeaders, getAccessToken, API_URL, DIRECT_API_URL } from "@/lib/api";

interface Paper {
  paper_id: string;
  title: string;
  arxiv_id?: string;
  authors?: string[];
  page_count?: number;
  chunk_count?: number;
  source?: string;
  created_at?: string;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function PapersPage() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'arxiv' | 'pdf'>('all');
  const [showAddModal, setShowAddModal] = useState(false);
  const [sourceType, setSourceType] = useState<'arxiv' | 'pdf'>('arxiv');
  const [arxivUrl, setArxivUrl] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isIndexing, setIsIndexing] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [indexSuccess, setIndexSuccess] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch papers
  useEffect(() => {
    fetchPapers();
  }, []);

  async function fetchPapers() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/papers`, { headers: await getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setPapers(data.papers || []);
      }
    } catch (error) {
      console.error('Failed to fetch papers:', error);
    } finally {
      setLoading(false);
    }
  }

  async function indexPaper() {
    setIsIndexing(true);
    setIndexError(null);
    setIndexSuccess(null);
    try {
      let res: Response;

      if (sourceType === 'arxiv') {
        if (!arxivUrl.trim()) return;

        res = await fetch(`${DIRECT_API_URL}/v1/papers/index`, {
          method: 'POST',
          headers: await getAuthHeaders(),
          body: JSON.stringify({
            url: arxivUrl.trim(),
            source_type: sourceType
          }),
        });
      } else {
        // PDF upload — use Authorization header but NOT Content-Type (FormData sets it)
        if (!selectedFile) return;

        const formData = new FormData();
        formData.append('file', selectedFile);

        const token = await getAccessToken();
        const uploadHeaders: HeadersInit = {};
        if (token) {
          (uploadHeaders as Record<string, string>)['Authorization'] = `Bearer ${token}`;
        }

        res = await fetch(`${DIRECT_API_URL}/v1/papers/upload`, {
          method: 'POST',
          headers: uploadHeaders,
          body: formData,
        });
      }

      if (res.ok) {
        const data = await res.json();
        setIndexSuccess(
          `indexed "${data.title || 'paper'}" — ${data.chunks || 0} chunks, ${data.pages || 0} pages`
        );
        setIsIndexing(false);
        setIsMinimized(false);
        setShowAddModal(true);
        fetchPapers();
        setTimeout(() => {
          setShowAddModal(false);
          resetModal();
        }, 2000);
      } else {
        const error = await res.json();
        setIndexError(error.detail || error.error || 'Unknown error');
        setIsIndexing(false);
      }
    } catch (error) {
      console.error('Failed to index paper:', error);
      setIndexError('Failed to index paper. Please try again.');
      setIsIndexing(false);
    }
  }

  async function removePaper(paperId: string) {
    if (!confirm('Remove this paper from your collection?')) return;

    setActionLoading(paperId);
    try {
      const res = await fetch(`${API_URL}/v1/papers/${paperId}`, {
        method: 'DELETE',
        headers: await getAuthHeaders(),
      });

      if (res.ok) {
        fetchPapers();
      }
    } catch (error) {
      console.error('Failed to remove paper:', error);
    } finally {
      setActionLoading(null);
    }
  }

  function resetModal() {
    setArxivUrl('');
    setSelectedFile(null);
    setSourceType('arxiv');
    setIndexError(null);
    setIndexSuccess(null);
    setIsIndexing(false);
    setIsMinimized(false);
  }

  // Filter papers
  const filteredPapers = papers.filter(p => {
    const paperType = p.arxiv_id ? 'arxiv' : 'pdf';
    if (filter !== 'all' && paperType !== filter) return false;
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      const matchesTitle = p.title?.toLowerCase().includes(query);
      const matchesArxiv = p.arxiv_id?.toLowerCase().includes(query);
      const matchesAuthors = p.authors?.some(a => a.toLowerCase().includes(query));
      if (!matchesTitle && !matchesArxiv && !matchesAuthors) return false;
    }
    return true;
  });

  // Current indexing label for minimized pill
  const indexingLabel = sourceType === 'arxiv'
    ? arxivUrl.replace(/https?:\/\/(www\.)?arxiv\.org\/(abs|pdf)\//, '').replace(/\.pdf$/, '')
    : selectedFile?.name || 'pdf';

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium lowercase mb-1">papers</h1>
          <p className="text-sm text-[#555] lowercase">research papers indexed via api & mcp</p>
        </div>
        <button
          onClick={() => { resetModal(); setShowAddModal(true); }}
          className="flex items-center gap-2 px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
        >
          <Plus size={14} />
          add paper
        </button>
      </div>

      {/* Card Container */}
      <div className="rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[#1a1a1a]">
          {/* Search */}
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="search papers..."
              className="w-full h-9 pl-9 pr-4 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#444] focus:outline-none focus:border-[#333] lowercase transition-colors"
            />
          </div>

          {/* Filter buttons */}
          <div className="flex items-center gap-1 p-1 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a]">
            {(['all', 'arxiv', 'pdf'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded text-xs lowercase transition-colors ${
                  filter === f
                    ? 'bg-[#1a1a1a] text-white'
                    : 'text-[#555] hover:text-white'
                }`}
              >
                {f === 'all' ? 'all' : f}
              </button>
            ))}
          </div>
        </div>

        {/* Papers List */}
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#333] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#444] lowercase">loading papers...</p>
          </div>
        ) : filteredPapers.length === 0 ? (
          <div className="p-12 text-center">
            <FileText size={32} className="text-[#222] mx-auto mb-3" />
            <h3 className="text-sm text-[#555] lowercase mb-1">no papers yet</h3>
            <p className="text-xs text-[#333] lowercase mb-4">
              add research papers from arxiv or upload pdfs to start using context.
            </p>
            <button
              onClick={() => { resetModal(); setShowAddModal(true); }}
              className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors"
            >
              add your first paper
            </button>
          </div>
        ) : (
          <div className="divide-y divide-[#1a1a1a]">
            {filteredPapers.map((paper) => (
              <div
                key={paper.paper_id}
                className="flex items-center gap-4 px-4 py-4 hover:bg-[#111] transition-colors group"
              >
                {/* Icon */}
                {(() => {
                  const isArxiv = !!paper.arxiv_id;
                  return (
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                      isArxiv ? 'bg-[#fa7315]/10' : 'bg-[#1a1a1a]'
                    }`}>
                      <FileText size={18} className={isArxiv ? 'text-[#fa7315]' : 'text-[#555]'} />
                    </div>
                  );
                })()}

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white truncate mb-1">
                    {paper.title || paper.arxiv_id || 'Untitled Paper'}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[#444]">
                    {(() => {
                      const isArxiv = !!paper.arxiv_id;
                      return (
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${
                          isArxiv ? 'bg-[#fa7315]/20 text-[#fa7315]' : 'bg-[#1a1a1a] text-[#666]'
                        }`}>
                          {isArxiv ? 'arxiv' : 'pdf'}
                        </span>
                      );
                    })()}
                    {paper.authors && paper.authors.length > 0 && (
                      <span className="truncate max-w-[200px]">
                        {paper.authors.slice(0, 2).join(', ')}{paper.authors.length > 2 ? ' et al.' : ''}
                      </span>
                    )}
                    {paper.page_count && paper.page_count > 0 && <span>{paper.page_count} pages</span>}
                    {paper.chunk_count && paper.chunk_count > 0 && <span>{paper.chunk_count} chunks</span>}
                  </div>
                </div>

                {/* Date */}
                <span className="text-xs text-[#333] flex-shrink-0">
                  {paper.created_at ? formatDate(paper.created_at) : '-'}
                </span>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {paper.arxiv_id && (
                    <a
                      href={`https://arxiv.org/abs/${paper.arxiv_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-white transition-colors"
                      title="View on arXiv"
                    >
                      <ExternalLink size={14} />
                    </a>
                  )}
                  <button
                    onClick={() => removePaper(paper.paper_id)}
                    disabled={actionLoading === paper.paper_id}
                    className="p-2 rounded-lg hover:bg-[#1a1a1a] text-[#444] hover:text-red-500 transition-colors disabled:opacity-50"
                    title="Remove paper"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Minimized Indexing Indicator — floating pill at bottom-right */}
      {isMinimized && isIndexing && (
        <button
          onClick={() => { setIsMinimized(false); setShowAddModal(true); }}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-3 pl-4 pr-3 py-3 rounded-2xl bg-[#0f0f0f] border border-[#1a1a1a] shadow-2xl shadow-black/40 hover:border-[#2a2a2a] transition-all group cursor-pointer max-w-xs"
        >
          {/* Animated spinner */}
          <RefreshCw size={16} className="text-[#fa7315] animate-spin flex-shrink-0" />

          {/* Info */}
          <div className="flex-1 min-w-0 text-left">
            <p className="text-xs font-medium text-white truncate lowercase">
              indexing paper...
            </p>
            <p className="text-[10px] text-[#444] truncate lowercase">
              {indexingLabel}
            </p>
          </div>

          {/* Expand icon */}
          <Maximize2 size={14} className="text-[#333] group-hover:text-[#fa7315] transition-colors flex-shrink-0" />
        </button>
      )}

      {/* Add Paper Modal */}
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
              <h2 className="text-lg font-medium lowercase">add paper</h2>
              <div className="flex items-center gap-1">
                {/* Minimize button — visible during indexing */}
                {isIndexing && (
                  <button
                    onClick={() => { setIsMinimized(true); setShowAddModal(false); }}
                    className="p-1.5 rounded-lg hover:bg-[#1a1a1a] text-[#555] hover:text-[#fa7315] transition-colors"
                    title="Minimize — indexing continues in the background"
                  >
                    <Minimize2 size={15} />
                  </button>
                )}
                {/* Close button — visible when not indexing */}
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

            {/* Form (hidden during indexing) */}
            {!isIndexing && !indexSuccess && (
              <>
                {/* Source Type Tabs */}
                <div className="flex gap-2 mb-6">
                  <button
                    onClick={() => setSourceType('arxiv')}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium transition-colors ${
                      sourceType === 'arxiv'
                        ? 'bg-[#fa7315]/10 border-[#fa7315]/30 text-[#fa7315]'
                        : 'bg-[#0a0a0a] border-[#1a1a1a] text-[#555] hover:text-white hover:border-[#333]'
                    }`}
                  >
                    <LinkIcon size={16} />
                    arXiv paper
                  </button>
                  <button
                    onClick={() => setSourceType('pdf')}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium transition-colors ${
                      sourceType === 'pdf'
                        ? 'bg-[#fa7315]/10 border-[#fa7315]/30 text-[#fa7315]'
                        : 'bg-[#0a0a0a] border-[#1a1a1a] text-[#555] hover:text-white hover:border-[#333]'
                    }`}
                  >
                    <Upload size={16} />
                    upload pdf
                  </button>
                </div>

                {sourceType === 'arxiv' ? (
                  <div className="mb-6">
                    <label className="block text-xs text-[#555] uppercase tracking-wider mb-2">arxiv url or id</label>
                    <input
                      type="text"
                      value={arxivUrl}
                      onChange={(e) => setArxivUrl(e.target.value)}
                      placeholder="e.g., 2301.07041 or https://arxiv.org/abs/2301.07041"
                      className="w-full h-10 px-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-sm text-white placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors"
                      autoFocus
                    />
                    <p className="text-[10px] text-[#333] mt-2">paste an arxiv url or paper id</p>
                  </div>
                ) : (
                  <div className="mb-6">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".pdf"
                      onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                      className="hidden"
                    />
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const file = e.dataTransfer.files[0];
                        if (file && file.type === 'application/pdf') {
                          setSelectedFile(file);
                        }
                      }}
                      className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
                        selectedFile
                          ? 'border-[#fa7315]/50 bg-[#fa7315]/5'
                          : 'border-[#1a1a1a] hover:border-[#333]'
                      }`}
                    >
                      {selectedFile ? (
                        <>
                          <FileText size={24} className="text-[#fa7315] mx-auto mb-3" />
                          <p className="text-sm text-white mb-1 truncate max-w-full px-2" title={selectedFile.name}>{selectedFile.name}</p>
                          <p className="text-xs text-[#555]">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                        </>
                      ) : (
                        <>
                          <Upload size={24} className="text-[#333] mx-auto mb-3" />
                          <p className="text-sm text-[#555] mb-1">drag & drop pdf here</p>
                          <p className="text-xs text-[#333]">or click to browse</p>
                        </>
                      )}
                    </div>
                    <p className="text-[10px] text-[#333] mt-2">max file size: 50mb</p>
                  </div>
                )}
              </>
            )}

            {/* Indexing progress */}
            {isIndexing && (
              <div className="mb-6">
                <div className="text-center mb-4">
                  <RefreshCw size={24} className="text-[#fa7315] animate-spin mx-auto mb-3" />
                  <p className="text-sm font-medium text-white lowercase mb-1">
                    indexing paper...
                  </p>
                  <p className="text-xs text-[#555] lowercase">
                    {sourceType === 'arxiv' ? `fetching & processing ${indexingLabel}` : `processing ${indexingLabel}`}
                  </p>
                </div>

                {/* Indeterminate progress bar */}
                <div className="h-2 bg-[#1a1a1a] rounded-full overflow-hidden mb-2">
                  <div className="h-full bg-[#fa7315] rounded-full animate-pulse" style={{ width: '60%' }} />
                </div>
                <p className="text-[10px] text-[#333] text-center lowercase">
                  this may take 1-2 minutes for embedding generation
                </p>

                {/* Minimize hint */}
                <p className="mt-4 text-[10px] text-[#333] text-center lowercase">
                  tip: click minimize or the backdrop to continue browsing while indexing
                </p>
              </div>
            )}

            {/* Success message */}
            {indexSuccess && (
              <div className="mb-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 text-sm text-green-400 lowercase">
                {indexSuccess}
              </div>
            )}

            {/* Error message */}
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
                  onClick={indexPaper}
                  disabled={(sourceType === 'arxiv' ? !arxivUrl.trim() : !selectedFile)}
                  className="px-4 py-2 bg-[#fa7315] text-black text-sm font-medium rounded-lg lowercase hover:bg-[#ff8c3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  index paper
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
