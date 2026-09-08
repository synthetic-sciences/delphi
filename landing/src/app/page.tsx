import { ArchitectureFigure, RetrievalFigure } from "@/components/Figures";

const GITHUB = "https://github.com/synthetic-sciences/delphi";
const NPM = "https://www.npmjs.com/package/@synsci/delphi";
const PYPI = "https://pypi.org/project/synsci-delphi-proxy/";
const README = `${GITHUB}#readme`;
const ENV_DOCS = `${GITHUB}/blob/master/docs/env-advanced.md`;

const SOURCES: [string, string][] = [
  ["Repositories", "Code search, symbols, call graphs, and the tests and documentation related to a file"],
  ["Documentation", "Versioned pages from documentation sites, with full-text search"],
  ["Papers", "Sections, citations, equations, and quoted evidence from arXiv or uploaded PDFs"],
  ["Datasets", "Hugging Face dataset cards and metadata"],
  ["Local folders", "Private, in-progress work that has no Git remote"],
];

const TOOLS: [string, string[]][] = [
  ["Indexing", ["index_repository", "index_local_folder", "index_paper", "index_dataset", "index_source"]],
  ["Search", ["search_code", "search_symbols", "search_papers", "grep_source", "search"]],
  ["Code structure", ["find_callers", "find_callees", "impact_analysis", "build_code_graph", "get_symbol"]],
  ["Context", ["build_context_pack", "get_context", "context_session_create", "context_session_handoff"]],
  ["Sources", ["resolve_source", "read_source", "tree_source", "check_freshness", "list_stale_sources"]],
  ["Research (opt-in)", ["research", "research_start", "research_status", "research_followup"]],
];

const UPDATES: [string, string][] = [
  [
    "Aug 2026",
    "Deterministic hybrid retrieval: identical searches return identical results. Agent mode now indexes generated source files. A file-level BM25 candidate source ships opt-in.",
  ],
  [
    "Jul 2026",
    "Immutable source snapshots, reproducible context sessions, durable connector synchronization, policy-gated web search and crawl, query expansion, and listwise reranking.",
  ],
  [
    "Jun 2026",
    "Code dependency graph (callers, callees, impact analysis), symbol extraction for eleven languages, local-folder indexing, index drift detection, and a lite deployment mode.",
  ],
];

function Caption({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <b>{label}:</b> {children}
    </>
  );
}

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#abstract">
        Skip to content
      </a>

      <main className="paper">
        <header className="titleblock">
          <p className="eyebrow">Open-source software</p>
          <h1>Delphi</h1>
          <p className="subtitle">A local-first context engine for coding agents</p>
          <p className="authors">Aayam Bansal</p>
          <p className="affiliation">
            <a href="https://syntheticsciences.ai">Synthetic Sciences</a>
          </p>
          <nav className="links" aria-label="Project links">
            <a href={GITHUB}>Code</a>
            <a href={NPM}>npm</a>
            <a href={PYPI}>PyPI</a>
            <a href={README}>Documentation</a>
          </nav>
        </header>

        <figure className="figure wide">
          <div className="figure-scroll">
            <ArchitectureFigure />
          </div>
          <figcaption>
            <Caption label="Figure 1">
              Delphi sits between a coding agent and the sources it works from. Everything is
              indexed into a PostgreSQL database on the user&apos;s machine and exposed over MCP.
            </Caption>
          </figcaption>
        </figure>

        <section className="abstract" id="abstract">
          <h2>Abstract</h2>
          <p>
            Coding agents work from what they can see, and most of what they need is not in their
            training data: the repository in front of them, the documentation for the exact library
            version it depends on, the paper a method came from. Delphi is an open-source context
            engine that indexes repositories, documentation sites, research papers, datasets, and
            local folders into a PostgreSQL database on the user&apos;s own machine and exposes them
            to any MCP client as a small set of tools for indexing, searching, following call
            graphs, and assembling context packs under a token budget. Retrieval fans a query out to
            six candidate sources, dense vectors, BM25 full text, trigram symbol matching, exact
            symbol and path lookup, and path tokens, and fuses them by reciprocal rank, so
            identifier-heavy and prose queries share one pipeline. Identical requests return
            identical results, completed indexing runs produce immutable snapshots, and saved
            context sessions record exactly which snapshot an agent used. No source content leaves
            the machine unless a remote provider is explicitly allowed.
          </p>
        </section>

        <section id="sources">
          <h2>
            <span className="num">1</span>
            <span>What Delphi indexes</span>
          </h2>
          <p>
            A source is anything an agent might need to read while working. Each source type has
            its own parser and produces the kind of context that is useful for it (Table 1).
            Repositories are cloned with Git and parsed with tree-sitter, so functions, classes,
            and their call relationships are available in addition to text. Documentation is
            crawled within the requested scope and kept per version. Papers are split into
            sections with their citations and equations preserved, so an agent can quote evidence
            with its anchor.
          </p>
          <div className="table-wrap">
            <p className="tablecaption">
              <Caption label="Table 1">Source types and the context available for each.</Caption>
            </p>
            <table className="booktabs">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Available context</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map(([source, context]) => (
                  <tr key={source}>
                    <td>{source}</td>
                    <td>{context}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Every index lives in the user&apos;s PostgreSQL database. When an indexing run
            completes, it publishes an immutable snapshot of the source; a failed or cancelled run
            leaves the previous snapshot searchable. Repositories can be indexed at a branch or at
            an exact commit, and a freshness check reports when a local folder or repository has
            drifted from its index.
          </p>
        </section>

        <section id="retrieval">
          <h2>
            <span className="num">2</span>
            <span>Retrieval</span>
          </h2>
          <p>
            Dense retrieval alone is a poor fit for code. An agent asking for{" "}
            <code>handleAuthCallback</code> should get that function on the first try, not a list
            of semantically similar middleware. Delphi therefore treats retrieval as candidate
            generation followed by fusion (Figure 2). A query is sent to six candidate sources at
            once: cosine similarity over pgvector embeddings, BM25 over a full-text index of the
            chunks, trigram similarity over symbol names for partial and misspelled identifiers,
            exact lookup of symbols by name or qualified name, exact lookup of files by path or
            glob, and an opt-in overlap between query tokens and normalized file paths.
          </p>
          <figure className="figure wide">
            <div className="figure-scroll">
              <RetrievalFigure />
            </div>
            <figcaption>
              <Caption label="Figure 2">
                The hybrid retrieval pipeline. Candidate sources are scored independently and fused
                by weighted reciprocal rank, because ranks are comparable across sources and raw
                scores are not.
              </Caption>
            </figcaption>
          </figure>
          <p>
            Candidates are fused by weighted reciprocal rank. A chunk found by several sources
            rises; a chunk found by one strong source is kept rather than averaged away. The fused
            list is diversified across files so a single large file cannot fill the result set,
            and it can optionally pass through a cross-encoder or a listwise reranker over the
            head of the list. Prose questions can optionally be expanded with a hypothetical
            document before embedding.
          </p>
          <h3>Determinism</h3>
          <p>
            An agent that reruns a search should see the same answer. Every candidate query has a
            total ordering, concurrent identical requests share a single execution, and the outputs
            of any optional model providers are cached on disk, so a search repeats exactly across
            requests and across restarts of the service. Vector search can run as an exact scan
            rather than an approximate index when exact repeatability matters more than latency.
          </p>
          <h3>Code structure</h3>
          <p>
            Symbol extraction runs through tree-sitter for Python, JavaScript, TypeScript, Go,
            Rust, Java, C, C++, C#, Ruby, and PHP. From the extracted definitions and references
            Delphi builds a dependency graph per repository, which answers who calls a function,
            what it calls, and what would be affected by changing it.
          </p>
          <h3>Context packs</h3>
          <p>
            A context pack takes a task description and a token budget and returns a ranked set of
            files and excerpts sized to fit the agent&apos;s next call, together with the snapshot
            each item came from. A context session saves that pack so another agent, or the same
            agent later, can rehydrate exactly the same view.
          </p>
        </section>

        <section id="interface">
          <h2>
            <span className="num">3</span>
            <span>Agent interface</span>
          </h2>
          <p>
            Delphi is an MCP server. Its tools are grouped, and a profile selects which groups are
            advertised to the agent, since every tool definition costs tokens on each handshake.
            The default <code>code</code> profile exposes repository indexing, search, code
            structure, and context tools; <code>papers</code>, <code>docs</code>,{" "}
            <code>minimal</code>, and <code>all</code> select other subsets. Table 2 lists
            representative tools.
          </p>
          <div className="table-wrap">
            <p className="tablecaption">
              <Caption label="Table 2">Representative MCP tools by group.</Caption>
            </p>
            <table className="booktabs">
              <thead>
                <tr>
                  <th scope="col">Group</th>
                  <th scope="col">Tools</th>
                </tr>
              </thead>
              <tbody>
                {TOOLS.map(([group, tools]) => (
                  <tr key={group}>
                    <td>{group}</td>
                    <td className="tool-list">
                      {tools.map((tool, i) => (
                        <span key={tool}>
                          <code>{tool}</code>
                          {i < tools.length - 1 ? ", " : ""}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            The same operations are available over HTTP at <code>localhost:8742</code>, and a local
            dashboard at <code>localhost:3000</code> shows indexed sources, jobs, and API keys.
          </p>
        </section>

        <section id="install">
          <h2>
            <span className="num">4</span>
            <span>Getting started</span>
          </h2>
          <p>
            The installer starts the local stack and can register Delphi with Claude Code, Cursor,
            Windsurf, or Claude Desktop. It needs Docker, Git, and one embeddings provider; the
            default local sentence-transformers model needs no API key.
          </p>
          <pre className="codeblock">
            <span className="prompt">$ </span>npx @synsci/delphi
          </pre>
          <pre className="codeblock">
            <span className="prompt">$ </span>delphi
            <span className="comment">            # open the dashboard</span>
            {"\n"}
            <span className="prompt">$ </span>delphi status
            <span className="comment">     # check the stack</span>
            {"\n"}
            <span className="prompt">$ </span>delphi logs -f
            <span className="comment">    # follow logs</span>
            {"\n"}
            <span className="prompt">$ </span>delphi stop
            <span className="comment">       # stop services</span>
          </pre>
          <p>
            Any other MCP client connects through a small stdio proxy. Create an API key in the
            dashboard, then add:
          </p>
          <pre className="codeblock">{`{
  "mcpServers": {
    "delphi": {
      "command": "uvx",
      "args": ["synsci-delphi-proxy"],
      "env": {
        "SYNSC_API_KEY": "your-api-key",
        "SYNSC_API_URL": "http://localhost:8742"
      }
    }
  }
}`}</pre>
          <p>
            To run from source, clone the <a href={GITHUB}>repository</a>, copy{" "}
            <code>env.example</code> to <code>.env</code>, and run{" "}
            <code>./scripts/launch_app.sh</code>. Configuration is documented in the{" "}
            <a href={ENV_DOCS}>advanced environment reference</a>.
          </p>
        </section>

        <section id="local">
          <h2>
            <span className="num">5</span>
            <span>Local-first execution</span>
          </h2>
          <p>
            The API, workers, database, and dashboard all run on the user&apos;s machine. The
            default network policy is <code>local_only</code>: no remote provider is called unless
            the deployment allowlists it, and a per-request policy can only narrow that ceiling,
            never widen it. Embeddings default to a local sentence-transformers model; OpenAI and
            Gemini embeddings, and a keyless hash embedding for constrained machines, are
            alternatives. Hosted web search and crawling exist but are off by default and, when
            enabled, send only the query, never indexed content.
          </p>
          <p>
            Delphi is licensed under Apache 2.0 and developed in the open at{" "}
            <a href={GITHUB}>github.com/synthetic-sciences/delphi</a>.
          </p>
        </section>

        <section id="updates">
          <h2>Updates</h2>
          <dl className="updates">
            {UPDATES.map(([date, text]) => (
              <div key={date}>
                <dt>{date}</dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section id="citation">
          <h2>Citation</h2>
          <pre className="codeblock">{`@software{delphi2026,
  title   = {Delphi: a local-first context engine for coding agents},
  author  = {Bansal, Aayam},
  year    = {2026},
  url     = {https://github.com/synthetic-sciences/delphi},
  license = {Apache-2.0}
}`}</pre>
        </section>

        <footer className="colophon">
          <div>
            <span>
              Delphi is a <a href="https://syntheticsciences.ai">Synthetic Sciences</a>
              {" project. "}
            </span>
            <span>&copy; {new Date().getFullYear()} InkVell Inc.</span>
          </div>
          <ul>
            <li>
              <a href={GITHUB}>GitHub</a>
            </li>
            <li>
              <a href={NPM}>npm</a>
            </li>
            <li>
              <a href="mailto:team@syntheticsciences.ai">Contact</a>
            </li>
            <li>
              <a href="https://syntheticsciences.ai/privacy">Privacy</a>
            </li>
            <li>
              <a href="https://syntheticsciences.ai/terms">Terms</a>
            </li>
          </ul>
        </footer>
      </main>
    </>
  );
}
