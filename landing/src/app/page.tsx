import Link from "next/link";
import { Faq } from "@/components/Faq";
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

const WHAT: [string, string][] = [
  ["Six-way retrieval", "Dense vectors, BM25, trigram symbols, exact symbols, paths, and path tokens, fused by reciprocal rank"],
  ["Deterministic", "The same query returns the same results across requests and restarts"],
  ["Call graphs", "Who calls a function, what it calls, and what changing it affects, for eleven languages"],
  ["Context packs", "Ranked files and excerpts sized to a token budget, with the snapshot each came from"],
  ["Immutable snapshots", "A finished index is a snapshot; a failed run leaves the previous one searchable"],
  ["Local by default", "API, workers, PostgreSQL, and dashboard on your machine; nothing leaves unless you allow it"],
];

const CLIENTS = ["Claude Code", "Cursor", "Windsurf", "Claude Desktop", "any MCP client"];

const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: "What is Delphi?",
    a: (
      <p>
        An open-source context engine that runs on your machine. It indexes repositories,
        documentation sites, research papers, datasets, and local folders into PostgreSQL, and
        exposes them to coding agents over MCP as tools for indexing, searching, following call
        graphs, and assembling context packs under a token budget.
      </p>
    ),
  },
  {
    q: "How do I install it?",
    a: (
      <p>
        Run <code>npx @synsci/delphi</code>. The installer starts the local stack and can register
        Delphi with Claude Code, Cursor, Windsurf, or Claude Desktop. It needs Docker and Git; the
        default embeddings model runs locally, so no API key is required. The{" "}
        <a href={README}>README</a> covers running from source.
      </p>
    ),
  },
  {
    q: "Which agents and editors work with it?",
    a: (
      <p>
        Any MCP client. Claude Code, Cursor, Windsurf, and Claude Desktop register in one step;
        everything else connects through the <code>synsci-delphi-proxy</code> stdio proxy. The same
        operations are available over HTTP at <code>localhost:8742</code>, and a dashboard at{" "}
        <code>localhost:3000</code> shows indexed sources, jobs, and API keys.
      </p>
    ),
  },
  {
    q: "Does my code leave my machine?",
    a: (
      <p>
        Not unless you allow it. The default network policy is <code>local_only</code>: no remote
        provider is called unless the deployment allowlists it, and a per-request policy can only
        narrow that ceiling. Hosted web search and crawling exist but are off by default and, when
        enabled, send only the query, never indexed content.
      </p>
    ),
  },
  {
    q: "Do I need an API key or a model subscription?",
    a: (
      <p>
        No. Embeddings default to a local sentence-transformers model, and retrieval works without
        any hosted model. OpenAI or Gemini embeddings, a cross-encoder or listwise reranker, and
        query expansion are optional and use your own keys if you turn them on.
      </p>
    ),
  },
  {
    q: "How is this different from vector search?",
    a: (
      <p>
        Dense retrieval alone is a poor fit for code: an agent asking for a function by name should
        get that function, not a list of semantically similar middleware. Delphi treats retrieval as
        candidate generation followed by fusion, so identifier-heavy and prose queries share one
        pipeline, and the fused list is diversified across files so one large file cannot fill it.
      </p>
    ),
  },
  {
    q: "Has the retrieval been evaluated?",
    a: (
      <p>
        Yes. <Link href="/research">Where Do Context-Engine Gains Come From?</Link> decomposes Delphi
        against conventional retrieval built from its own parts, on SWE-bench Verified instances its
        development never saw, and releases the code, per-case artifacts, exposure ledger, and all
        620 agent trajectories. It claims no state of the art and reports its null results with the
        same prominence as the positive ones.
      </p>
    ),
  },
  {
    q: "What does it cost, and how is it licensed?",
    a: (
      <p>
        Delphi is free and open source under <a href={LICENSE}>Apache 2.0</a>. The only costs are
        those of hosted providers you choose to enable, billed by them directly.
      </p>
    ),
  },
];

function Arrow() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6.5 12L17 12M13 16.5L17.5 12L13 7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
    </svg>
  );
}

export default function Home() {
  return (
    <div className="site">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <div className="container">
        <header className="top">
          <Link href="/" className="wordmark" aria-label="Delphi home">
            <Mark size={26} />
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
            <a href={README} className="cta">
              Get started
              <Arrow />
            </a>
          </nav>
        </header>

        <main id="main">
          <section className="hero">
            <a className="kicker" href={LICENSE}>
              Open source under Apache 2.0
            </a>
            <h1>A local-first context engine for coding agents</h1>
            <p className="lede">
              Delphi indexes your repositories, documentation, papers, datasets, and local folders
              into PostgreSQL on your own machine.
              <span className="br" />
              It serves search, call graphs, and context packs to any MCP client, and nothing you
              index leaves the machine unless you allow it.
            </p>
            <Install />
          </section>

          <figure className="fig">
            <div className="fig-scroll">
              <HeroFigure />
            </div>
            <figcaption>
              <b>Fig. 1</b>
              How a search runs. One query fans out to six candidate sources, their rankings fuse by
              reciprocal rank into one list, and the same query replayed returns the same list.
            </figcaption>
          </figure>

          <section className="section" id="what">
            <div className="section-title">
              <h2>What is Delphi?</h2>
              <p>
                Delphi is an open-source context engine that gives a coding agent the files,
                symbols, and documents it needs, from an index that lives on your machine.
              </p>
            </div>
            <ul className="list">
              {WHAT.map(([term, body]) => (
                <li key={term}>
                  <span className="marker">•</span>
                  <div>
                    <strong>{term}</strong>
                    {body}
                  </div>
                </li>
              ))}
            </ul>
            <a href={DOCS} className="button">
              <span>Read the docs</span>
              <Arrow />
            </a>
          </section>

          <section className="section" id="research">
            <div className="section-title">
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
            </div>
            <figure className="fig inset">
              <div className="fig-scroll">
                <FactorialChart />
              </div>
              <figcaption>
                <b>Fig. 2</b>
                Candidate pool × learned reranking on 98 SWE-bench Verified instances that
                development never saw. Delphi&apos;s pool leads before reranking; the rerankers close
                the MRR gap but not the recall gap.
              </figcaption>
            </figure>
            <div className="buttons">
              <Link href="/research" className="button">
                <span>Read the paper</span>
                <Arrow />
              </Link>
              <a href={PDF} className="button-light">
                <span>PDF</span>
              </a>
              <a href={BENCHMARK} className="button-light">
                <span>Code and artifacts</span>
              </a>
              <a href={DATASET} className="button-light">
                <span>620 agent trajectories</span>
              </a>
            </div>
          </section>

          <section className="section" id="agents">
            <div className="section-title">
              <h2>Plugs into the agent you already use</h2>
              <p>
                The installer registers Delphi with your editor in one step; every other MCP client
                connects through a small stdio proxy. Tools are grouped into profiles (
                <code>code</code>, <code>papers</code>, <code>docs</code>, <code>minimal</code>,{" "}
                <code>all</code>) so the handshake only advertises what the agent needs.
              </p>
            </div>
            <ul className="clients" aria-label="Supported clients">
              {CLIENTS.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
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
            <figure className="fig inset">
              <div className="fig-scroll">
                <ArchitectureFigure />
              </div>
              <figcaption>
                <b>Fig. 3</b>
                Everything runs on the user&apos;s machine: the agent talks to Delphi over MCP, and
                Delphi indexes sources into PostgreSQL with pgvector.
              </figcaption>
            </figure>
          </section>

          <section className="section faq" id="faq">
            <div className="section-title">
              <h2>FAQ</h2>
            </div>
            <ul>
              {FAQ.map((item) => (
                <li key={item.q}>
                  <Faq question={item.q}>{item.a}</Faq>
                </li>
              ))}
            </ul>
          </section>
        </main>

        <p className="giant" aria-hidden="true">
          Delphi
        </p>

        <footer className="footer">
          <div className="cell">
            <a href={GITHUB}>
              GitHub
              <Stars repo="synthetic-sciences/delphi" />
            </a>
          </div>
          <div className="cell">
            <a href={DOCS}>Docs</a>
          </div>
          <div className="cell">
            <a href={NPM}>npm</a>
          </div>
          <div className="cell">
            <a href={PYPI}>PyPI</a>
          </div>
          <div className="cell">
            <Link href="/research">Research</Link>
          </div>
          <div className="cell">
            <a href={SYNTHETIC_SCIENCES}>Synthetic Sciences</a>
          </div>
        </footer>
      </div>

      <div className="legal">
        <span>
          &copy; {new Date().getFullYear()} <a href={SYNTHETIC_SCIENCES}>Synthetic Sciences</a>
        </span>
        <span>
          <a href="mailto:team@syntheticsciences.ai">Contact</a>
        </span>
        <span>
          <a href="https://syntheticsciences.ai/privacy">Privacy</a>
        </span>
        <span>
          <a href="https://syntheticsciences.ai/terms">Terms</a>
        </span>
        <span>
          <a href={LICENSE}>Apache 2.0</a>
        </span>
      </div>
    </div>
  );
}
