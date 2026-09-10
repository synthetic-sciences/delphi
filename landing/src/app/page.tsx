import Link from "next/link";
import { ArchitectureFigure, FactorialChart, HeroFigure } from "@/components/Figures";
import { Install } from "@/components/Install";
import { Mark } from "@/components/Mark";
import { Stars } from "@/components/Stars";
import { ThemeToggle } from "@/components/ThemeToggle";

const GITHUB = "https://github.com/synthetic-sciences/delphi";
const DOCS = `${GITHUB}/tree/master/docs`;
const README = `${GITHUB}#readme`;
const LICENSE = `${GITHUB}/blob/master/LICENSE`;
const NPM = "https://www.npmjs.com/package/@synsci/delphi";
const PYPI = "https://pypi.org/project/synsci-delphi-proxy/";
const SYNTHETIC_SCIENCES = "https://syntheticsciences.ai";
const BENCHMARK = "https://github.com/aayambansal/delphi-benchmark";
const DATASET = "https://huggingface.co/datasets/aayambansall/delphi-benchmark-traces";
const PDF = "/papers/context-engine-gains.pdf";

const SPEC: [string, React.ReactNode][] = [
  [
    "Six-way retrieval",
    <>
      Dense vectors, BM25 full text, trigram symbol matching, exact symbol and path lookup, and
      path tokens run on every query and are fused by reciprocal rank, so{" "}
      <code>handleAuthCallback</code> and &ldquo;where is auth handled&rdquo; take the same route.
    </>,
  ],
  [
    "Deterministic",
    <>
      Every candidate query has a total ordering, identical concurrent requests share one
      execution, and model outputs are cached on disk. A search repeats exactly across requests
      and across restarts.
    </>,
  ],
  [
    "Call graphs",
    <>
      tree-sitter extracts symbols for Python, TypeScript, Go, Rust, Java, C, C++, C#, Ruby, and
      PHP; Delphi builds a dependency graph per repository: who calls a function, what it calls,
      and what changing it would affect.
    </>,
  ],
  [
    "Context packs",
    <>
      Give a task and a token budget; get ranked files and excerpts sized to the agent&apos;s next
      call, each tagged with the snapshot it came from. A saved session lets another agent
      rehydrate the same view.
    </>,
  ],
  [
    "Immutable snapshots",
    <>
      A finished indexing run publishes a snapshot; a failed one leaves the previous snapshot
      searchable. Index a branch or an exact commit, and a freshness check reports drift.
    </>,
  ],
  [
    "Local by default",
    <>
      API, workers, PostgreSQL, and dashboard run on your machine. The network policy defaults to{" "}
      <code>local_only</code>, embeddings default to a local model, and nothing you index leaves
      the machine unless you allow a provider.
    </>,
  ],
];

const CLIENTS = ["Claude Code", "Cursor", "Windsurf", "Claude Desktop", "any MCP client"];

const FAQ: [string, React.ReactNode][] = [
  [
    "What is Delphi?",
    <>
      An open-source context engine that runs on your machine. It indexes repositories,
      documentation sites, research papers, datasets, and local folders into PostgreSQL, and
      exposes them to coding agents over MCP as tools for indexing, searching, following call
      graphs, and assembling context packs under a token budget.
    </>,
  ],
  [
    "How do I install it?",
    <>
      Run <code>npx @synsci/delphi</code>. The installer starts the local stack and can register
      Delphi with Claude Code, Cursor, Windsurf, or Claude Desktop. It needs Docker and Git; the
      default embeddings model runs locally, so no API key is required. The{" "}
      <a href={README}>README</a> covers running from source.
    </>,
  ],
  [
    "Which agents and editors work with it?",
    <>
      Any MCP client. Claude Code, Cursor, Windsurf, and Claude Desktop register in one step;
      everything else connects through the <code>synsci-delphi-proxy</code> stdio proxy. The same
      operations are available over HTTP at <code>localhost:8742</code>, and a dashboard at{" "}
      <code>localhost:3000</code> shows indexed sources, jobs, and API keys.
    </>,
  ],
  [
    "Does my code leave my machine?",
    <>
      Not unless you allow it. The default network policy is <code>local_only</code>: no remote
      provider is called unless the deployment allowlists it, and a per-request policy can only
      narrow that ceiling. Hosted web search and crawling exist but are off by default and, when
      enabled, send only the query, never indexed content.
    </>,
  ],
  [
    "Do I need an API key or a model subscription?",
    <>
      No. Embeddings default to a local sentence-transformers model, and retrieval works without
      any hosted model. OpenAI or Gemini embeddings, a cross-encoder or listwise reranker, and
      query expansion are optional and use your own keys if you turn them on.
    </>,
  ],
  [
    "How is this different from vector search?",
    <>
      Dense retrieval alone is a poor fit for code: an agent asking for a function by name should
      get that function, not a list of semantically similar middleware. Delphi treats retrieval as
      candidate generation followed by fusion, so identifier-heavy and prose queries share one
      pipeline, and the fused list is diversified across files so one large file cannot fill it.
    </>,
  ],
  [
    "Has the retrieval been evaluated?",
    <>
      Yes. <Link href="/research">Where Do Context-Engine Gains Come From?</Link> decomposes Delphi
      against conventional retrieval built from its own parts, on SWE-bench Verified instances its
      development never saw, and releases the code, per-case artifacts, exposure ledger, and all
      620 agent trajectories. It claims no state of the art and reports its null results with the
      same prominence as the positive ones.
    </>,
  ],
  [
    "What does it cost, and how is it licensed?",
    <>
      Delphi is free and open source under <a href={LICENSE}>Apache 2.0</a>. The only costs are
      those of hosted providers you choose to enable, billed by them directly.
    </>,
  ],
];

export default function Home() {
  return (
    <div className="site">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="top">
        <div className="measure">
          <Link href="/" className="wordmark" aria-label="Delphi home">
            <Mark size={24} />
            <span>Delphi</span>
          </Link>
          <nav className="nav" aria-label="Site">
            <Link href="/research">Research</Link>
            <a href={DOCS} className="optional">
              Docs
            </a>
            <a href={GITHUB}>GitHub</a>
            <a href={NPM} className="optional">
              npm
            </a>
            <ThemeToggle />
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="hero">
          <div className="measure">
            <div className="hero-copy">
              <a className="kicker" href={LICENSE}>
                open source, Apache 2.0
              </a>
              <h1>A local-first context engine for coding agents</h1>
              <p className="lede">
                Delphi indexes your repositories, documentation, papers, datasets, and local
                folders into PostgreSQL on your own machine.
              </p>
              <p className="lede">
                It serves search, call graphs, and context packs to any MCP client, and nothing
                you index leaves the machine unless you allow it.
              </p>
              <Install />
            </div>
            <div className="hero-art">
              <HeroFigure />
            </div>
          </div>
        </section>

        <section className="band" id="what">
          <div className="measure">
            <h2>What Delphi does</h2>
            <dl className="spec">
              {SPEC.map(([term, body]) => (
                <div key={term} style={{ display: "contents" }}>
                  <dt>{term}</dt>
                  <dd>{body}</dd>
                </div>
              ))}
            </dl>
            <div className="actions">
              <a href={DOCS} className="button-light">
                Read the docs
              </a>
            </div>
          </div>
        </section>

        <section className="band" id="research">
          <div className="measure">
            <h2>Where the gains come from</h2>
            <div className="prose">
              <p>
                We decomposed Delphi against conventional retrieval built from its own parts, on
                SWE-bench Verified instances its development never saw. The advantage is the
                candidate pool, not the reranker: Delphi&apos;s candidates lead by{" "}
                <strong>+0.19 MRR</strong> and <strong>+0.07 Recall@20</strong> before any
                reranking. The shared rerankers help the weaker conventional pool more, so after
                reranking MRR ties while the recall gap (<strong>+0.09</strong>) stays.
              </p>
              <p>
                The pool advantage comes from chunking, indexing, and weighting rather than any
                single structural branch, and it inverts on commit-to-files queries. The paper
                claims no state of the art and gives its null results the same billing as the
                positive ones.
              </p>
            </div>
            <figure className="fig">
              <div className="fig-scroll">
                <FactorialChart />
              </div>
              <figcaption>
                <b>Fig. 1</b>
                Candidate pool × learned reranking on 98 SWE-bench Verified instances that
                development never saw. Outlined bars are the candidates alone; filled bars have
                Delphi&apos;s rerankers attached.
              </figcaption>
            </figure>
            <div className="actions">
              <Link href="/research" className="button">
                Read the paper
              </Link>
              <a href={PDF} className="button-light">
                PDF
              </a>
              <a href={BENCHMARK} className="button-light">
                Code and artifacts
              </a>
              <a href={DATASET} className="button-light">
                620 agent trajectories
              </a>
            </div>
          </div>
        </section>

        <section className="band" id="agents">
          <div className="measure">
            <h2>Plugs into the agent you already use</h2>
            <div className="agents">
              <div className="prose">
                <p>
                  The installer registers Delphi with your editor in one step; every other MCP
                  client connects through a small stdio proxy. Tools are grouped into profiles (
                  <code>code</code>, <code>papers</code>, <code>docs</code>, <code>minimal</code>,{" "}
                  <code>all</code>) so the handshake only advertises what the agent needs.
                </p>
                <ul className="clients" aria-label="Supported clients">
                  {CLIENTS.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
              <pre className="code">{`{
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
            </div>
            <figure className="fig">
              <div className="fig-scroll">
                <ArchitectureFigure />
              </div>
              <figcaption>
                <b>Fig. 2</b>
                Everything runs on the user&apos;s machine: the agent talks to Delphi over MCP, and
                Delphi indexes sources into PostgreSQL with pgvector.
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="band" id="faq">
          <div className="measure">
            <h2>Questions</h2>
            <div className="faq">
              {FAQ.map(([q, a]) => (
                <details key={q}>
                  <summary>{q}</summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>
      </main>

      <div className="measure">
        <p className="giant" aria-hidden="true">
          Delphi
        </p>
      </div>
      <footer className="foot">
        <div className="measure">
          <ul>
            <li>
              <a href={GITHUB}>
                GitHub
                <Stars repo="synthetic-sciences/delphi" />
              </a>
            </li>
            <li>
              <a href={DOCS}>Docs</a>
            </li>
            <li>
              <a href={NPM}>npm</a>
            </li>
            <li>
              <a href={PYPI}>PyPI</a>
            </li>
            <li>
              <Link href="/research">Research</Link>
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
          <span>
            &copy; {new Date().getFullYear()} <a href={SYNTHETIC_SCIENCES}>Synthetic Sciences</a>.
            Apache 2.0.
          </span>
        </div>
      </footer>
    </div>
  );
}
