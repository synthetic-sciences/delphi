import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import { InstallChip } from "@/components/InstallChip";
import { ThemeToggle } from "@/components/ThemeToggle";

const sourceTypes = ["repositories", "documentation", "papers", "datasets", "local folders"];

const files = [
  ["backend/synsc/auth/sessions.py", "session lifetime and cookie policy"],
  ["backend/synsc/api/http_server.py", "login route and response headers"],
  ["backend/tests/test_auth.py", "the behavior the change must keep"],
];

function Arrow() {
  return (
    <svg aria-hidden="true" fill="none" height="10" viewBox="0 0 14 10" width="14">
      <path d="M0 5h12M8.5 1 13 5l-4.5 4" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function ContextConstellation() {
  const nodes = [
    [82, 88, 6], [184, 54, 4], [285, 116, 7], [402, 66, 4], [522, 132, 6],
    [640, 72, 4], [728, 166, 7], [126, 228, 5], [250, 262, 4], [370, 210, 8],
    [492, 286, 4], [616, 236, 6], [712, 330, 4], [184, 374, 7], [330, 350, 4],
    [472, 408, 6], [610, 382, 4],
  ];
  const edges = [
    [0, 1], [0, 7], [1, 2], [2, 3], [2, 9], [3, 4], [4, 5], [4, 11],
    [5, 6], [6, 12], [7, 8], [7, 13], [8, 9], [9, 10], [9, 14], [10, 11],
    [10, 15], [11, 12], [12, 16], [13, 14], [14, 15], [15, 16],
  ];

  return (
    <svg aria-hidden="true" className="constellation" viewBox="0 0 800 470">
      {edges.map(([a, b], index) => (
        <line key={index} x1={nodes[a][0]} x2={nodes[b][0]} y1={nodes[a][1]} y2={nodes[b][1]} />
      ))}
      {nodes.map(([x, y, radius], index) => (
        <g key={index} transform={`translate(${x} ${y})`}>
          <circle className="node-glow" r={radius * 4} />
          <circle className={index === 9 ? "node node-active" : "node"} r={radius} />
          <circle className="node-center" r="1.25" />
        </g>
      ))}
      <g className="constellation-label" transform="translate(300 176)">
        <rect height="34" width="142" />
        <text x="15" y="21">local context index</text>
      </g>
      <g className="constellation-label constellation-label-small" transform="translate(558 208)">
        <rect height="29" width="104" />
        <text x="13" y="18">related tests</text>
      </g>
    </svg>
  );
}

function SearchWindow() {
  return (
    <figure className="product-window" aria-label="A Delphi search returning source files">
      <div className="window-chrome">
        <span className="window-dots" aria-hidden="true"><i /><i /><i /></span>
        <span>localhost:3000/search</span>
        <span className="window-state">local</span>
      </div>
      <div className="window-body">
        <aside className="source-rail">
          <div className="rail-label">Sources</div>
          {[
            ["D", "delphi", "indexed"],
            ["S", "synsc docs", "indexed"],
            ["P", "saved papers", "indexed"],
          ].map(([letter, name, state], index) => (
            <div className={index === 0 ? "source-item source-item-active" : "source-item"} key={name}>
              <span>{letter}</span>
              <div><strong>{name}</strong><small>{state}</small></div>
            </div>
          ))}
        </aside>
        <div className="search-pane">
          <div className="query-box">
            <span>Ask Delphi</span>
            <p>Where is session expiry enforced?</p>
          </div>
          <div className="result-meta"><span>3 files</span><span>18 ms</span></div>
          <div className="result-list">
            {files.map(([path, note], index) => (
              <div className="result-file" key={path}>
                <span>0{index + 1}</span>
                <div><strong>{path}</strong><small>{note}</small></div>
                <b aria-hidden="true">↗</b>
              </div>
            ))}
          </div>
        </div>
      </div>
    </figure>
  );
}

function SourceIndex() {
  const rows = [
    ["repositories", "12", "72%"],
    ["documentation", "186", "91%"],
    ["papers", "42", "56%"],
    ["datasets", "9", "34%"],
    ["local folders", "6", "48%"],
  ];
  return (
    <figure className="index-ledger" aria-label="Sources in a local Delphi index">
      <div className="visual-pill"><BrandMark className="visual-pill-mark" /> delphi / sources</div>
      <div className="ledger-body">
        {rows.map(([name, count, width]) => (
          <div className="ledger-row" key={name}>
            <span>{name}</span>
            <i><b style={{ width }} /></i>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
      <figcaption><span><i /> private</span><span><i /> on this machine</span></figcaption>
    </figure>
  );
}

function ContextPack() {
  return (
    <figure className="context-pack" aria-label="A Delphi context pack with cited files">
      <div className="visual-pill"><BrandMark className="visual-pill-mark" /> context pack / auth</div>
      <div className="pack-question">Where is session expiry enforced, and which test covers it?</div>
      <div className="pack-answer">
        <p>Session expiry is checked when the signed cookie is decoded, before the request context is created.</p>
        <div className="code-line"><span>124</span><code>session = verify_session_cookie(cookie)</code></div>
        <div className="code-line"><span>125</span><code>if session.expires_at &lt; now:</code></div>
        <div className="code-line code-line-active"><span>126</span><code>raise SessionExpired()</code></div>
      </div>
      <div className="pack-sources">
        <span>sessions.py : 124–126</span>
        <span>test_auth.py : 219</span>
      </div>
    </figure>
  );
}

function Terminal() {
  return (
    <div className="terminal" aria-label="Installing and starting Delphi">
      <div><span>$</span> npx @synsci/delphi</div>
      <p>✓ local stack ready</p>
      <p>✓ dashboard http://localhost:3000</p>
      <p>✓ MCP clients configured</p>
      <div><span>$</span> <i /></div>
    </div>
  );
}

export default function Home() {
  return (
    <main id="top">
      <section className="atlas-hero">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-glow" aria-hidden="true" />
        <ContextConstellation />

        <div className="hero-frame">
          <header className="hero-header">
            <ThemeToggle />
            <Link className="hero-brand" href="/" aria-label="Delphi home">
              <BrandMark className="hero-brand-mark" />
              <span>delphi</span>
              <small>by Synthetic Sciences</small>
            </Link>
          </header>

          <div className="hero-copy">
            <p className="eyebrow">Local context for coding agents</p>
            <h1>Your agent should read the repo first.</h1>
            <p className="hero-dek">Delphi searches your code, docs, and papers before the agent answers.</p>
            <div className="hero-actions">
              <InstallChip />
              <Link className="outline-link" href="https://github.com/synthetic-sciences/delphi">
                GitHub <Arrow />
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="source-strip" aria-label="Supported source types">
        <p>One index for</p>
        <div className="source-marquee">
          {[...sourceTypes, ...sourceTypes].map((source, index) => (
            <span aria-hidden={index >= sourceTypes.length} key={`${source}-${index}`}>
              {source}<i />
            </span>
          ))}
        </div>
      </section>

      <section className="statement-section" id="search">
        <div className="statement-panel dither-warm">
          <p className="eyebrow">Delphi search</p>
          <h2>The agent cannot see your work.</h2>
          <p>Delphi finds the implementation and the tests that cover it before the agent edits anything.</p>
        </div>
        <SearchWindow />
      </section>

      <section className="detail-section">
        <div className="detail-heading">
          <p className="eyebrow">The index</p>
          <h2>One search layer.</h2>
          <p>Private sources stay on infrastructure you control.</p>
        </div>
        <SourceIndex />
        <div className="feature-grid">
          {[
            ["Code aware", "Follow symbols to their callers and tests."],
            ["Source aware", "Search a repo alongside its docs and papers."],
            ["Agent ready", "Connect Claude Code, Codex, Cursor, or any MCP client."],
          ].map(([title, body], index) => (
            <article key={title}>
              <span>0{index + 1}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="statement-section statement-section-reverse" id="context">
        <ContextPack />
        <div className="statement-panel dither-coral">
          <p className="eyebrow">Context packs</p>
          <h2>Answers need file paths.</h2>
          <p>Delphi returns file paths with each answer.</p>
        </div>
      </section>

      <section className="local-section" id="local">
        <div>
          <p className="eyebrow">Local by default</p>
          <h2>Run it on your machine.</h2>
          <p>Start Delphi locally. Then point your MCP client at the sources you want indexed.</p>
          <Link className="text-link" href="https://github.com/synthetic-sciences/delphi#install">
            Installation guide <Arrow />
          </Link>
        </div>
        <Terminal />
      </section>

      <section className="final-cta" id="install">
        <div className="final-cta-inner">
          <div>
            <p className="eyebrow">Open source · Apache 2.0</p>
            <h2>Start with one command.</h2>
          </div>
          <InstallChip />
        </div>
      </section>

      <footer className="atlas-footer">
        <div className="footer-grid">
          <div className="footer-intro">
            <div><BrandMark className="footer-mark" /><span>delphi</span></div>
            <p>Local context for coding agents, by Synthetic Sciences.</p>
          </div>
          <div>
            <h3>Product</h3>
            <ul>
              <li><a href="#search">Search</a></li>
              <li><a href="#context">Context packs</a></li>
              <li><a href="#local">Local stack</a></li>
              <li><a href="#install">Install</a></li>
            </ul>
          </div>
          <div>
            <h3>Resources</h3>
            <ul>
              <li><a href="https://www.npmjs.com/package/@synsci/delphi">npm</a></li>
              <li><a href="https://github.com/synthetic-sciences/delphi">GitHub</a></li>
              <li><a href="https://github.com/synthetic-sciences/delphi#readme">README</a></li>
              <li><a href="https://modelcontextprotocol.io">MCP</a></li>
            </ul>
          </div>
          <div>
            <h3>Company</h3>
            <ul>
              <li><a href="https://syntheticsciences.ai">Synthetic Sciences ↗</a></li>
              <li><a href="mailto:team@syntheticsciences.ai">Contact</a></li>
              <li><a href="https://syntheticsciences.ai/privacy">Privacy</a></li>
              <li><a href="https://syntheticsciences.ai/terms">Terms</a></li>
            </ul>
          </div>
        </div>
        <div className="footer-meta">
          <span>© {new Date().getFullYear()} InkVell Inc. Delphi is a Synthetic Sciences product.</span>
          <a href="#top">Back to top ↑</a>
        </div>
        <div className="footer-wordmark" aria-hidden="true">delphi</div>
      </footer>
    </main>
  );
}
