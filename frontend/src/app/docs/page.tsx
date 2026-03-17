"use client";

import { useState } from "react";
import Link from "next/link";
import PageShell from "@/components/PageShell";
import {
  Book, Code, Key, Terminal, Webhook, Zap, Copy, Check,
  ChevronRight, GitBranch, FileText, Search,
  FileCode, FlaskConical, ArrowLeft, Link2, Github,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Code block with copy button                                       */
/* ------------------------------------------------------------------ */
function CodeBlock({ code, lang = "bash" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative group rounded-lg bg-[#f7f0e8] border border-[#dfcdbf] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#dfcdbf]">
        <span className="text-[10px] text-[#a09488] uppercase tracking-wider">{lang}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="p-1 rounded hover:bg-[#dfcdbf] text-[#a09488] hover:text-[#695954] transition-colors"
        >
          {copied ? <Check size={12} className="text-[#d06e28]" /> : <Copy size={12} />}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto text-xs font-mono text-[#695954] leading-relaxed whitespace-pre">{code}</pre>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Endpoint row                                                       */
/* ------------------------------------------------------------------ */
function Endpoint({
  method,
  path,
  desc,
  body,
  response,
}: {
  method: "GET" | "POST" | "DELETE";
  path: string;
  desc: string;
  body?: string;
  response?: string;
}) {
  const [open, setOpen] = useState(false);
  const methodStyles =
    method === "GET"
      ? "text-[#9a3f10] border-[#9a3f10]/40"
      : method === "POST"
      ? "text-[#d06e28] border-[#d06e28]/50 bg-[#faebd5]/60"
      : "text-[#7a2e0c] border-[#7a2e0c]/50";

  return (
    <div className="rounded-lg border border-[#dfcdbf] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[#efe7dd] transition-colors text-left"
      >
        <span className={`w-16 text-center py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider bg-transparent flex-shrink-0 ${methodStyles}`}>
          {method}
        </span>
        <code className="text-sm font-mono text-[#2e2522] flex-1">{path}</code>
        <span className="text-xs text-[#a09488] hidden sm:block">{desc}</span>
        <ChevronRight size={14} className={`text-[#a09488] transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-[#dfcdbf]">
          {/* Summary row */}
          <table className="w-full text-xs border-b border-[#dfcdbf]">
            <tbody>
              <tr>
                <td className="px-4 py-2.5 text-[#8a7a72] w-24 align-top">endpoint</td>
                <td className="px-4 py-2.5 font-mono text-[#2e2522]">{method} {path}</td>
              </tr>
              <tr>
                <td className="px-4 py-2.5 text-[#8a7a72] w-24 align-top border-t border-[#dfcdbf]/50">description</td>
                <td className="px-4 py-2.5 text-[#695954] border-t border-[#dfcdbf]/50">{desc}</td>
              </tr>
              {body && (
                <tr>
                  <td className="px-4 py-2.5 text-[#8a7a72] w-24 align-top border-t border-[#dfcdbf]/50">content-type</td>
                  <td className="px-4 py-2.5 font-mono text-[#695954] border-t border-[#dfcdbf]/50">application/json</td>
                </tr>
              )}
            </tbody>
          </table>

          {/* Body & Response — side by side when both exist */}
          {body && response ? (
            <div className="grid grid-cols-2 divide-x divide-[#dfcdbf]">
              <div className="p-4">
                <p className="text-[10px] text-[#8a7a72] uppercase tracking-wider mb-2 font-medium">request body</p>
                <CodeBlock code={body} lang="json" />
              </div>
              <div className="p-4">
                <p className="text-[10px] text-[#8a7a72] uppercase tracking-wider mb-2 font-medium">response</p>
                <CodeBlock code={response} lang="json" />
              </div>
            </div>
          ) : (
            <div className="p-4">
              {body && (
                <div>
                  <p className="text-[10px] text-[#8a7a72] uppercase tracking-wider mb-2 font-medium">request body</p>
                  <CodeBlock code={body} lang="json" />
                </div>
              )}
              {response && (
                <div>
                  <p className="text-[10px] text-[#8a7a72] uppercase tracking-wider mb-2 font-medium">response</p>
                  <CodeBlock code={response} lang="json" />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Section nav item                                                   */
/* ------------------------------------------------------------------ */
const sections = [
  { id: "introduction", label: "introduction", icon: Book },
  { id: "authentication", label: "authentication", icon: Key },
  { id: "quickstart", label: "quick start", icon: Terminal },
  { id: "integrations", label: "integrations", icon: Link2 },
  { id: "repositories", label: "repositories api", icon: GitBranch },
  { id: "code-search", label: "code search", icon: Search },
  { id: "symbols", label: "symbols", icon: FileCode },
  { id: "files", label: "files", icon: FileText },
  { id: "papers", label: "papers api", icon: FlaskConical },
  { id: "paper-search", label: "paper search", icon: Search },
  { id: "mcp", label: "mcp setup", icon: Zap },
];

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */
export default function DocsPage() {
  const [activeSection, setActiveSection] = useState("introduction");

  function scrollTo(id: string) {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <PageShell>
      <div className="flex gap-8">
        {/* Sidebar nav */}
        <nav className="hidden lg:block w-48 flex-shrink-0 sticky top-0 self-start pt-1">
          <Link
            href="/overview"
            className="flex items-center gap-1.5 px-2 py-1.5 mb-4 text-xs text-[#b58a73] hover:text-[#ff8c3a] rounded-md hover:bg-[#b58a73]/10 transition-colors"
          >
            <ArrowLeft size={12} />
            back to home
          </Link>
          <p className="text-[10px] text-[#a09488] uppercase tracking-wider mb-3 px-2">on this page</p>
          <ul className="space-y-0.5">
            {sections.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => scrollTo(s.id)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-colors text-left ${
                    activeSection === s.id
                      ? "text-[#b58a73] bg-[#b58a73]/10"
                      : "text-[#8a7a72] hover:text-[#2e2522] hover:bg-[#efe7dd]"
                  }`}
                >
                  <s.icon size={12} />
                  {s.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-12">
          {/* -------------------------------------------------------- */}
          {/*  INTRODUCTION                                            */}
          {/* -------------------------------------------------------- */}
          <section id="introduction">
            <h1 className="text-2xl font-medium lowercase mb-2">documentation</h1>
            <p className="text-sm text-[#8a7a72] leading-relaxed mb-6">
              synsc context provides deep semantic understanding of code repositories and research papers.
              use the rest api or mcp server to index, search, and retrieve context for your ai agents.
            </p>
            <div className="grid sm:grid-cols-3 gap-3">
              <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
                <GitBranch size={18} className="text-[#b58a73] mb-2" />
                <h3 className="text-sm font-medium mb-1">code context</h3>
                <p className="text-xs text-[#a09488]">index github repos, semantic code search, symbol extraction</p>
              </div>
              <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
                <FlaskConical size={18} className="text-[#b58a73] mb-2" />
                <h3 className="text-sm font-medium mb-1">paper context</h3>
                <p className="text-xs text-[#a09488]">index arxiv papers, extract citations, equations, search semantically</p>
              </div>
              <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
                <Zap size={18} className="text-[#b58a73] mb-2" />
                <h3 className="text-sm font-medium mb-1">mcp native</h3>
                <p className="text-xs text-[#a09488]">model context protocol support for cursor, claude, and more</p>
              </div>
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  AUTHENTICATION                                          */}
          {/* -------------------------------------------------------- */}
          <section id="authentication">
            <h2 className="text-lg font-medium lowercase mb-2">authentication</h2>
            <p className="text-sm text-[#8a7a72] mb-4">
              all api requests require a bearer token. you can use either your session token
              (set automatically after login) or a generated api key from the{" "}
              <a href="/api-keys" className="text-[#b58a73] hover:underline">api keys</a> page.
            </p>
            <CodeBlock
              code={`curl -H "Authorization: Bearer YOUR_API_KEY" \\
  http://localhost:8742/v1/repositories`}
            />
            <div className="mt-4 p-3 rounded-lg bg-[#b58a73]/5 border border-[#b58a73]/20 text-xs text-[#695954]">
              <strong className="text-[#b58a73]">tip:</strong> create a dedicated api key for each integration
              (cursor, claude, scripts) so you can revoke them independently.
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  QUICK START                                             */}
          {/* -------------------------------------------------------- */}
          <section id="quickstart">
            <h2 className="text-lg font-medium lowercase mb-2">quick start</h2>
            <p className="text-sm text-[#8a7a72] mb-4">get running in under 5 minutes.</p>

            <div className="space-y-4">
              <div>
                <p className="text-xs text-[#8a7a72] mb-2 font-medium">1. create an api key</p>
                <p className="text-xs text-[#a09488] mb-2">
                  go to <a href="/api-keys" className="text-[#b58a73] hover:underline">api keys</a> and create a new key.
                  copy it — you won&apos;t see it again.
                </p>
              </div>

              <div>
                <p className="text-xs text-[#8a7a72] mb-2 font-medium">2. index a repository</p>
                <CodeBlock
                  code={`curl -X POST http://localhost:8742/v1/repositories/index \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"url": "facebook/react", "branch": "main"}'`}
                />
              </div>

              <div>
                <p className="text-xs text-[#8a7a72] mb-2 font-medium">3. search your code</p>
                <CodeBlock
                  code={`curl -X POST http://localhost:8742/v1/search/code \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "how does reconciliation work", "top_k": 5}'`}
                />
              </div>

              <div>
                <p className="text-xs text-[#8a7a72] mb-2 font-medium">4. index a paper</p>
                <CodeBlock
                  code={`curl -X POST http://localhost:8742/v1/papers/index \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"arxiv_id": "1706.03762"}'`}
                />
              </div>
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  INTEGRATIONS                                             */}
          {/* -------------------------------------------------------- */}
          <section id="integrations">
            <h2 className="text-lg font-medium lowercase mb-2">integrations</h2>
            <p className="text-sm text-[#8a7a72] mb-4">
              connect third-party accounts to unlock additional capabilities like private repository indexing.
            </p>

            {/* GitHub */}
            <div className="rounded-xl bg-[#faf5ef] border border-[#dfcdbf] overflow-hidden mb-6">
              <div className="flex items-center gap-3 px-4 py-3 border-b border-[#dfcdbf]">
                <Github size={16} className="text-[#2e2522]" />
                <h3 className="text-sm font-medium">github</h3>
              </div>
              <div className="p-4 space-y-3 text-xs text-[#8a7a72]">
                <p>
                  connect your github account to index <strong className="text-[#2e2522]">private repositories</strong>.
                  synsc context uses a fine-grained personal access token (pat) with read-only
                  access to clone and index your code.
                </p>

                <div className="space-y-2">
                  <p className="text-[10px] text-[#a09488] uppercase tracking-wider font-medium">setup</p>
                  <div className="flex items-start gap-3">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[#b58a73]/20 text-[#b58a73] text-[10px] font-bold flex items-center justify-center mt-0.5">1</span>
                    <p>
                      go to{" "}
                      <a href="https://github.com/settings/tokens?type=beta" target="_blank" rel="noopener noreferrer" className="text-[#b58a73] hover:underline">
                        github token settings
                      </a>{" "}
                      and create a <strong className="text-[#2e2522]">fine-grained personal access token</strong>
                    </p>
                  </div>
                  <div className="flex items-start gap-3">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[#b58a73]/20 text-[#b58a73] text-[10px] font-bold flex items-center justify-center mt-0.5">2</span>
                    <p>
                      set repository access to <strong className="text-[#2e2522]">&quot;only select repositories&quot;</strong> and
                      grant <code className="text-[#b58a73]">contents:read</code> permission
                    </p>
                  </div>
                  <div className="flex items-start gap-3">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[#b58a73]/20 text-[#b58a73] text-[10px] font-bold flex items-center justify-center mt-0.5">3</span>
                    <p>
                      go to <a href="/api-keys#github-token" className="text-[#b58a73] hover:underline">api keys &rarr; connect accounts</a> and
                      paste your token
                    </p>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-white/[0.03] border border-[#dfcdbf] text-xs text-[#a09488] space-y-1.5 mt-3">
                  <p>&bull; tokens are encrypted (aes) before storage and never exposed via any api endpoint</p>
                  <p>&bull; decrypted only in-memory at clone time, then immediately discarded</p>
                  <p>&bull; private repo data is fully isolated — other users cannot see or search your code</p>
                  <p>&bull; revoke anytime from the dashboard or directly on github</p>
                </div>
              </div>
            </div>

            {/* API endpoints */}
            <p className="text-xs text-[#8a7a72] mb-3">
              you can also manage your github connection programmatically:
            </p>
            <div className="space-y-2">
              <Endpoint
                method="GET"
                path="/v1/github/token"
                desc="Check if a GitHub token is configured"
                response={`{
  "has_token": true,
  "github_username": "octocat",
  "label": "personal",
  "last_used_at": "2026-02-13T...",
  "created_at": "2026-02-01T..."
}`}
              />
              <Endpoint
                method="POST"
                path="/v1/github/token"
                desc="Save or update a GitHub PAT"
                body={`{
  "token": "github_pat_...",    // fine-grained PAT
  "label": "personal"           // optional label
}`}
                response={`{
  "success": true,
  "github_username": "octocat"
}`}
              />
              <Endpoint
                method="DELETE"
                path="/v1/github/token"
                desc="Delete your stored GitHub token"
                response={`{
  "success": true,
  "message": "Token deleted"
}`}
              />
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  REPOSITORIES API                                        */}
          {/* -------------------------------------------------------- */}
          <section id="repositories">
            <h2 className="text-lg font-medium lowercase mb-2">repositories api</h2>
            <p className="text-sm text-[#8a7a72] mb-4">index github repositories and manage your indexed collection.</p>

            <div className="space-y-2">
              <Endpoint
                method="POST"
                path="/v1/repositories/index"
                desc="Index a GitHub repository"
                body={`{
  "url": "facebook/react",   // owner/repo or full GitHub URL
  "branch": "main"           // branch to index (default: main)
}`}
                response={`{
  "success": true,
  "repo_id": "499cb5cb-...",
  "owner": "facebook",
  "name": "react",
  "branch": "main",
  "files_indexed": 1240,
  "chunks_created": 3200,
  "symbols_extracted": 890
}`}
              />

              <Endpoint
                method="POST"
                path="/v1/repositories/index/stream"
                desc="Index with real-time SSE progress updates"
                body={`{
  "url": "facebook/react",
  "branch": "main"
}`}
                response={`// Server-Sent Events stream:
data: {"stage": "cloning", "message": "Cloning repository...", "progress": 10}
data: {"stage": "indexing", "message": "Processing files...", "progress": 45, "files_processed": 120, "total_files": 1240}
data: {"stage": "complete", "progress": 100, "result": {"files_indexed": 1240, "chunks_created": 3200}}`}
              />

              <Endpoint
                method="GET"
                path="/v1/repositories"
                desc="List all indexed repositories"
                response={`{
  "success": true,
  "repositories": [
    {
      "repo_id": "499cb5cb-...",
      "owner": "facebook",
      "name": "react",
      "branch": "main",
      "files_count": 1240,
      "chunks_count": 3200,
      "languages": {"javascript": 65.2, "typescript": 34.8}
    }
  ],
  "total": 1
}`}
              />

              <Endpoint
                method="GET"
                path="/v1/repositories/{repo_id}"
                desc="Get detailed repository information"
                response={`{
  "success": true,
  "repo_id": "499cb5cb-...",
  "stats": {
    "files_count": 1240,
    "chunks_count": 3200,
    "symbols_count": 890,
    "total_lines": 245000,
    "total_tokens": 1850000
  },
  "languages": {"javascript": 65.2, "typescript": 34.8}
}`}
              />

              <Endpoint
                method="DELETE"
                path="/v1/repositories/{repo_id}"
                desc="Delete a repository and all its indexed data"
                response={`{
  "success": true,
  "message": "Repository deleted"
}`}
              />
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  CODE SEARCH                                             */}
          {/* -------------------------------------------------------- */}
          <section id="code-search">
            <h2 className="text-lg font-medium lowercase mb-2">code search</h2>
            <p className="text-sm text-[#8a7a72] mb-4">semantic code search across your indexed repositories using vector embeddings.</p>

            <Endpoint
              method="POST"
              path="/v1/search/code"
              desc="Semantic code search"
              body={`{
  "query": "how does authentication work",  // natural language query
  "repo_ids": ["499cb5cb-..."],             // optional: filter by repos
  "language": "python",                      // optional: filter by language
  "top_k": 10                                // results to return (1-100)
}`}
              response={`{
  "success": true,
  "results": [
    {
      "repo_name": "owner/repo",
      "file_path": "src/auth.py",
      "content": "def authenticate(token): ...",
      "start_line": 42,
      "end_line": 68,
      "language": "python",
      "relevance_score": 0.89
    }
  ],
  "count": 10,
  "search_time_ms": 245
}`}
            />
          </section>

          {/* -------------------------------------------------------- */}
          {/*  SYMBOLS                                                  */}
          {/* -------------------------------------------------------- */}
          <section id="symbols">
            <h2 className="text-lg font-medium lowercase mb-2">symbols</h2>
            <p className="text-sm text-[#8a7a72] mb-4">search for functions, classes, and methods extracted during indexing.</p>

            <Endpoint
              method="POST"
              path="/v1/symbols/search"
              desc="Search extracted code symbols"
              body={`{
  "name": "authenticate",         // symbol name (optional)
  "repo_ids": ["499cb5cb-..."],   // optional: filter by repos
  "symbol_type": "function",      // optional: function, class, method
  "language": "python",           // optional: filter by language
  "top_k": 25,                    // results per page
  "offset": 0                     // pagination offset
}`}
              response={`{
  "success": true,
  "symbols": [
    {
      "symbol_id": "ce971692-...",
      "name": "authenticate",
      "symbol_type": "function",
      "signature": "def authenticate(token: str) -> User:",
      "docstring": "Authenticate a user by token.",
      "file_path": "src/auth.py",
      "start_line": 42,
      "end_line": 68,
      "language": "python"
    }
  ],
  "total": 156,
  "has_more": true
}`}
            />
          </section>

          {/* -------------------------------------------------------- */}
          {/*  FILES                                                    */}
          {/* -------------------------------------------------------- */}
          <section id="files">
            <h2 className="text-lg font-medium lowercase mb-2">files</h2>
            <p className="text-sm text-[#8a7a72] mb-4">retrieve file content from indexed repositories.</p>

            <Endpoint
              method="POST"
              path="/v1/files/get"
              desc="Get file content from a repository"
              body={`{
  "repo_id": "499cb5cb-...",      // repository ID
  "file_path": "src/auth.py",    // path within the repo
  "start_line": 1,                // optional: start line (1-indexed)
  "end_line": 50                   // optional: end line
}`}
              response={`{
  "success": true,
  "repo_id": "499cb5cb-...",
  "file_path": "src/auth.py",
  "content": "import jwt\\ndef authenticate(token): ...",
  "language": "python",
  "total_lines": 131
}`}
            />
          </section>

          {/* -------------------------------------------------------- */}
          {/*  PAPERS API                                              */}
          {/* -------------------------------------------------------- */}
          <section id="papers">
            <h2 className="text-lg font-medium lowercase mb-2">papers api</h2>
            <p className="text-sm text-[#8a7a72] mb-4">index research papers from arxiv or pdf uploads. extract citations and equations.</p>

            <div className="space-y-2">
              <Endpoint
                method="POST"
                path="/v1/papers/index"
                desc="Index a paper from arXiv"
                body={`{
  "arxiv_id": "1706.03762",       // arXiv paper ID
  "source_type": "arxiv"          // "arxiv" or "pdf"
}`}
                response={`{
  "success": true,
  "paper_id": "abc123-...",
  "title": "Attention Is All You Need",
  "authors": ["Vaswani et al."],
  "sections_count": 12,
  "citations_count": 45,
  "equations_count": 8
}`}
              />

              <Endpoint
                method="POST"
                path="/v1/papers/upload"
                desc="Upload and index a PDF file"
                body={`// multipart/form-data
// field: file (PDF)`}
                response={`{
  "success": true,
  "paper_id": "abc123-...",
  "title": "Uploaded Paper",
  "sections_count": 8
}`}
              />

              <Endpoint
                method="GET"
                path="/v1/papers"
                desc="List all indexed papers"
                response={`{
  "success": true,
  "papers": [
    {
      "paper_id": "abc123-...",
      "title": "Attention Is All You Need",
      "authors": ["Vaswani et al."],
      "source": "arxiv",
      "indexed_at": "2026-02-10T..."
    }
  ],
  "total": 5
}`}
              />

              <Endpoint
                method="GET"
                path="/v1/papers/{paper_id}/citations"
                desc="Extract citations from an indexed paper"
                response={`{
  "success": true,
  "citations": [
    {"id": "1", "text": "Bahdanau et al., 2014", "title": "Neural Machine Translation..."}
  ]
}`}
              />

              <Endpoint
                method="GET"
                path="/v1/papers/{paper_id}/equations"
                desc="Extract equations from an indexed paper"
                response={`{
  "success": true,
  "equations": [
    {"id": "1", "latex": "\\\\text{Attention}(Q,K,V) = \\\\text{softmax}(QK^T/\\\\sqrt{d_k})V", "context": "Scaled dot-product attention"}
  ]
}`}
              />

              <Endpoint
                method="DELETE"
                path="/v1/papers/{paper_id}"
                desc="Delete a paper from your library"
                response={`{
  "success": true,
  "message": "Paper deleted"
}`}
              />
            </div>
          </section>

          {/* -------------------------------------------------------- */}
          {/*  PAPER SEARCH                                            */}
          {/* -------------------------------------------------------- */}
          <section id="paper-search">
            <h2 className="text-lg font-medium lowercase mb-2">paper search</h2>
            <p className="text-sm text-[#8a7a72] mb-4">semantic search across your indexed research papers.</p>

            <Endpoint
              method="POST"
              path="/v1/search/papers"
              desc="Semantic paper search"
              body={`{
  "query": "transformer attention mechanism",
  "top_k": 10,
  "paper_ids": ["abc123-..."]    // optional: filter by papers
}`}
              response={`{
  "success": true,
  "results": [
    {
      "paper_id": "abc123-...",
      "title": "Attention Is All You Need",
      "section": "3.2 Scaled Dot-Product Attention",
      "content": "We compute the dot products of the query...",
      "relevance_score": 0.92
    }
  ]
}`}
            />
          </section>

          {/* -------------------------------------------------------- */}
          {/*  MCP SETUP                                               */}
          {/* -------------------------------------------------------- */}
          <section id="mcp">
            <h2 className="text-lg font-medium lowercase mb-2">mcp integration</h2>
            <p className="text-sm text-[#8a7a72] mb-4">
              delphi implements the{" "}
              <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener noreferrer" className="text-[#b58a73] hover:underline">
                model context protocol
              </a>{" "}
              via streamable http. your agent connects directly to the server — no proxy, no extra process.
            </p>

            <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf] mb-8">
              <Webhook size={18} className="text-[#b58a73] mb-2" />
              <h3 className="text-sm font-medium mb-1">streamable http transport</h3>
              <p className="text-xs text-[#a09488]">
                your agent connects directly to <code className="text-[#b58a73]">http://localhost:8742/mcp</code> over http.
                authentication via <code className="text-[#b58a73]">Authorization: Bearer</code> header.
                responses stream via server-sent events (sse).
              </p>
            </div>

            {/* ---- PER-AGENT CONFIGS ---- */}
            <h3 className="text-xs text-[#8a7a72] font-medium uppercase tracking-wider mb-3">setup by agent</h3>

            <div className="space-y-6">
              {/* Claude Code */}
              <div>
                <p className="text-xs text-[#2e2522] font-medium mb-2 flex items-center gap-2">
                  <Terminal size={12} className="text-[#b58a73]" />
                  claude code
                </p>
                <CodeBlock lang="json" code={`// .mcp.json (in your project root)
{
  "mcpServers": {
    "delphi": {
      "type": "http",
      "url": "http://localhost:8742/mcp",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}`} />
                <p className="text-[11px] text-[#a09488] mt-2">
                  place in project root for project-scoped, or in <code className="text-[#695954]">~/.claude.json</code> for global.
                  restart claude code after editing.
                </p>
              </div>

              {/* Cursor */}
              <div>
                <p className="text-xs text-[#2e2522] font-medium mb-2 flex items-center gap-2">
                  <Code size={12} className="text-[#b58a73]" />
                  cursor
                </p>
                <CodeBlock lang="json" code={`// ~/.cursor/mcp.json
{
  "mcpServers": {
    "delphi": {
      "url": "http://localhost:8742/mcp",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}`} />
                <p className="text-[11px] text-[#a09488] mt-2">restart cursor after editing.</p>
              </div>

              {/* Windsurf */}
              <div>
                <p className="text-xs text-[#2e2522] font-medium mb-2 flex items-center gap-2">
                  <Code size={12} className="text-[#b58a73]" />
                  windsurf
                </p>
                <CodeBlock lang="json" code={`// ~/.codeium/windsurf/mcp_config.json
{
  "mcpServers": {
    "delphi": {
      "serverUrl": "http://localhost:8742/mcp",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}`} />
                <p className="text-[11px] text-[#a09488] mt-2">
                  windsurf uses <code className="text-[#695954]">serverUrl</code> instead of <code className="text-[#695954]">url</code>.
                  restart windsurf after editing.
                </p>
              </div>

              {/* Claude Desktop */}
              <div>
                <p className="text-xs text-[#2e2522] font-medium mb-2 flex items-center gap-2">
                  <Terminal size={12} className="text-[#b58a73]" />
                  claude desktop
                </p>
                <CodeBlock lang="json" code={`// claude_desktop_config.json
{
  "mcpServers": {
    "delphi": {
      "url": "http://localhost:8742/mcp",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}`} />
                <p className="text-[11px] text-[#a09488] mt-2">
                  macos: <code className="text-[#695954]">~/Library/Application Support/Claude/claude_desktop_config.json</code>{" · "}
                  linux: <code className="text-[#695954]">~/.config/Claude/claude_desktop_config.json</code>.
                  restart claude desktop after editing.
                </p>
              </div>
            </div>

            {/* ---- AVAILABLE TOOLS ---- */}
            <h3 className="text-xs text-[#8a7a72] font-medium uppercase tracking-wider mb-2 mt-8">available tools</h3>
            <p className="text-xs text-[#8a7a72] mb-3">
              once connected, your ai agent can use any of these tools:
            </p>
            <div className="grid sm:grid-cols-2 gap-2 mb-4">
              {[
                { name: "index_repository", desc: "Index a GitHub repository" },
                { name: "list_repositories", desc: "List indexed repositories" },
                { name: "get_repository", desc: "Get repository details" },
                { name: "delete_repository", desc: "Delete a repository" },
                { name: "remove_from_collection", desc: "Remove repo from your collection" },
                { name: "search_code", desc: "Semantic code search" },
                { name: "get_file", desc: "Get file content" },
                { name: "search_symbols", desc: "Find functions, classes" },
                { name: "get_symbol", desc: "Get symbol details" },
                { name: "get_directory_structure", desc: "Get repo directory tree" },
                { name: "analyze_repository", desc: "Deep code analysis" },
                { name: "index_paper", desc: "Index from arXiv or PDF" },
                { name: "list_papers", desc: "List indexed papers" },
                { name: "get_paper", desc: "Get full paper content" },
                { name: "delete_paper", desc: "Delete a paper" },
                { name: "search_papers", desc: "Semantic paper search" },
                { name: "get_citations", desc: "Extract citations" },
                { name: "get_equations", desc: "Extract equations" },
                { name: "get_code_snippets", desc: "Extract code blocks from papers" },
                { name: "generate_report", desc: "Generate markdown report" },
                { name: "compare_papers", desc: "Compare 2-5 papers side-by-side" },
                { name: "index_dataset", desc: "Index HuggingFace dataset card" },
                { name: "list_datasets", desc: "List indexed datasets" },
                { name: "get_dataset", desc: "Get dataset details" },
                { name: "search_datasets", desc: "Semantic dataset search" },
                { name: "delete_dataset", desc: "Delete a dataset" },
              ].map((tool) => (
                <div key={tool.name} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[#faf5ef] border border-[#dfcdbf]">
                  <Code size={12} className="text-[#b58a73] flex-shrink-0" />
                  <div>
                    <code className="text-xs font-mono text-[#2e2522]">{tool.name}</code>
                    <p className="text-[10px] text-[#a09488]">{tool.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* spacer */}
          <div className="h-16" />
        </div>
      </div>
    </PageShell>
  );
}
