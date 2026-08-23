import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import { ThemedImage } from "@/components/HeroImage";
import { InstallChip } from "@/components/InstallChip";
import { ThemeToggle } from "@/components/ThemeToggle";

const SOURCES = [
  "Repositories",
  "Documentation",
  "Papers",
  "Datasets",
  "Local folders",
] as const;

const CONTEXT_FILES = [
  ["backend/synsc/auth/sessions.py", "cookie validation"],
  ["backend/synsc/api/http_server.py", "request path"],
  ["backend/tests/test_auth.py", "expected behavior"],
] as const;

const FOOTER_COLUMNS = [
  {
    title: "Product",
    links: [
      ["Context", "#context"],
      ["Sources", "#sources"],
      ["Local stack", "#local"],
      ["Install", "#install"],
    ],
  },
  {
    title: "Resources",
    links: [
      ["npm", "https://www.npmjs.com/package/@synsci/delphi"],
      ["GitHub", "https://github.com/synthetic-sciences/delphi"],
      ["README", "https://github.com/synthetic-sciences/delphi#readme"],
      ["MCP", "https://modelcontextprotocol.io"],
    ],
  },
  {
    title: "Company",
    links: [
      ["Synthetic Sciences", "https://syntheticsciences.ai"],
      ["Contact", "mailto:team@syntheticsciences.ai"],
      ["Privacy", "https://syntheticsciences.ai/privacy"],
      ["Terms", "https://syntheticsciences.ai/terms"],
    ],
  },
] as const;

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <main id="main-content">
        <section className="atlas-hero" id="top">
          <div className="hero-media">
            <ThemedImage variant="sacred-way" priority />
          </div>
          <div className="hero-wash" aria-hidden="true" />

          <div className="page-shell hero-shell">
            <div className="hero-identity hero-rise">
              <ThemeToggle />
              <div>
                <Link className="brand-lockup" href="/" aria-label="Delphi home">
                  <BrandMark className="brand-lockup-mark" />
                  <span>Delphi</span>
                </Link>
                <Link className="made-by" href="https://syntheticsciences.ai">
                  by Synthetic Sciences
                </Link>
              </div>
            </div>

            <div className="hero-copy">
              <h1 className="hero-rise hero-rise-one">
                The right context,
                <br />
                before the code.
              </h1>
              <p className="hero-rise hero-rise-two">
                Delphi finds the files your coding agent needs and returns precise, cited context.
              </p>
              <div className="hero-actions hero-rise hero-rise-three">
                <InstallChip />
                <Link className="secondary-action" href="https://github.com/synthetic-sciences/delphi">
                  GitHub
                </Link>
              </div>
            </div>
          </div>
        </section>

        <section className="source-strip" aria-label="Supported source types">
          <div className="page-shell source-strip-inner">
            <p>Indexes</p>
            <div>
              {SOURCES.map((source) => (
                <span key={source}>{source}</span>
              ))}
            </div>
          </div>
        </section>

        <section className="statement-section" id="context">
          <div className="page-shell statement-grid">
            <div className="statement-copy section-reveal">
              <p className="section-label">Delphi context</p>
              <h2>See what the agent should see.</h2>
              <p>
                Search code, docs, papers, and local folders as one corpus. Every result links back to its source.
              </p>
            </div>

            <figure className="engraving-frame section-reveal">
              <ThemedImage variant="archive" />
            </figure>
          </div>
        </section>

        <section className="detail-section" id="sources">
          <div className="page-shell">
            <div className="section-heading section-reveal">
              <h2>Ask once. Get the files.</h2>
              <p>A compact context pack, ready for the next tool call.</p>
            </div>

            <div className="context-grid">
              <article className="context-card query-card section-reveal">
                <p className="card-kicker">Example query</p>
                <blockquote>Where is session expiry enforced?</blockquote>
                <div className="context-files">
                  {CONTEXT_FILES.map(([path, note]) => (
                    <div key={path}>
                      <code>{path}</code>
                      <span>{note}</span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="context-card source-card section-reveal">
                <div>
                  <p className="card-kicker">One index</p>
                  <h3>Every source stays distinct.</h3>
                </div>
                <ul>
                  {SOURCES.map((source) => (
                    <li key={source}>{source}</li>
                  ))}
                </ul>
              </article>

              <article className="context-card local-card section-reveal" id="local">
                <div>
                  <p className="card-kicker">Local by default</p>
                  <h3>Your sources stay where they live.</h3>
                  <p>Run the stack on your machine and choose exactly what gets indexed.</p>
                </div>
                <code>npx @synsci/delphi</code>
              </article>

              <article className="context-card mcp-card section-reveal">
                <div>
                  <p className="card-kicker">MCP</p>
                  <h3>Works with the agent you already use.</h3>
                </div>
                <p>Connect Delphi to Codex, Claude Code, Cursor, or any MCP client.</p>
              </article>
            </div>
          </div>
        </section>

        <section className="install-section" id="install">
          <div className="page-shell">
            <div className="install-panel section-reveal">
              <div>
                <h2>Source first.</h2>
                <p>Open source, self-hosted, and ready in one command.</p>
              </div>
              <div className="install-actions">
                <InstallChip />
                <Link className="secondary-action" href="https://github.com/synthetic-sciences/delphi#readme">
                  Read the README
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="page-shell footer-shell">
          <div className="footer-grid">
            <div className="footer-intro">
              <div className="footer-brand">
                <BrandMark className="footer-mark" />
                <span>Delphi</span>
              </div>
              <p>Local context for coding agents, by Synthetic Sciences.</p>
            </div>

            {FOOTER_COLUMNS.map((column) => (
              <div className="footer-column" key={column.title}>
                <h3>{column.title}</h3>
                <ul>
                  {column.links.map(([label, href]) => (
                    <li key={label}>
                      <Link href={href}>{label}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="footer-meta">
            <span>© {new Date().getFullYear()} InkVell Inc. Delphi is a Synthetic Sciences product.</span>
            <Link href="#top">Back to top</Link>
          </div>
        </div>
        <div className="footer-wordmark" aria-hidden="true">
          delphi
        </div>
      </footer>
    </>
  );
}
