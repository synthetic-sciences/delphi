import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import { ThemedImage } from "@/components/HeroImage";
import { InstallChip } from "@/components/InstallChip";
import { ThemeToggle } from "@/components/ThemeToggle";

const SOURCE_TYPES = [
  ["Repositories", "Symbols, callers, tests, and the code between them."],
  ["Documentation", "Reference pages kept with their heading structure."],
  ["Papers", "Methods, equations, citations, and implementation notes."],
  ["Datasets", "Cards, configs, and the details that shape a result."],
  ["Local folders", "Private notes and internal material on your machine."],
] as const;

const CONTEXT_FILES = [
  ["backend/synsc/auth/sessions.py", "cookie validation"],
  ["backend/synsc/api/http_server.py", "request handling"],
  ["backend/tests/test_auth.py", "expected behavior"],
] as const;

const FOOTER_COLUMNS = [
  {
    title: "Product",
    links: [
      ["Sources", "#sources"],
      ["Context", "#context"],
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
        <section className="heritage-hero" id="top">
          <div className="hero-art">
            <ThemedImage variant="sacred-way" priority />
          </div>
          <div className="hero-image-wash" aria-hidden="true" />

          <header className="hero-nav">
            <Link className="brand-lockup" href="/" aria-label="Delphi home">
              <BrandMark className="brand-lockup-mark" />
              <span>Delphi</span>
            </Link>

            <nav aria-label="Primary navigation">
              <Link href="https://github.com/synthetic-sciences/delphi">GitHub</Link>
              <Link href="#install">Install</Link>
              <ThemeToggle />
            </nav>
          </header>

          <div className="hero-copy-card">
            <p className="eyebrow">Context for coding agents</p>
            <h1>Context before code.</h1>
            <p className="hero-dek">
              Delphi finds the right source files before your coding agent answers.
            </p>
            <div className="hero-actions">
              <InstallChip />
              <Link className="text-action" href="https://github.com/synthetic-sciences/delphi">
                View source <span aria-hidden="true">↗</span>
              </Link>
            </div>
          </div>
        </section>

        <section className="source-ribbon" aria-label="Supported sources">
          <p>Search across</p>
          <div>
            {SOURCE_TYPES.slice(0, 4).map(([name]) => (
              <span key={name}>{name}</span>
            ))}
          </div>
        </section>

        <section className="source-section reveal" id="sources">
          <div className="section-intro">
            <p className="eyebrow">One local index</p>
            <h2>Your work, in one place.</h2>
            <p>
              Connect the sources an agent needs. Delphi keeps every answer tied to the files that support it.
            </p>
          </div>

          <div className="source-ledger">
            {SOURCE_TYPES.map(([name, description]) => (
              <article key={name}>
                <h3>{name}</h3>
                <p>{description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="context-section" id="context">
          <div className="context-heading reveal">
            <h2>Ask once. Get the files.</h2>
            <p>
              Delphi searches across source types, then returns a compact context pack with citations.
            </p>
          </div>

          <figure className="context-example reveal">
            <blockquote>Where is session expiry enforced?</blockquote>
            <figcaption>
              {CONTEXT_FILES.map(([path, note]) => (
                <div key={path}>
                  <code>{path}</code>
                  <span>{note}</span>
                </div>
              ))}
            </figcaption>
          </figure>
        </section>

        <section className="local-section reveal" id="local">
          <div>
            <h2>Run Delphi where your sources live.</h2>
            <p>
              Start the stack locally, index a source, and connect any MCP client.
            </p>
          </div>

          <div className="local-steps">
            <div><span>Install</span><code>npx @synsci/delphi</code></div>
            <div><span>Index</span><p>Add a repository, doc site, paper, or folder.</p></div>
            <div><span>Connect</span><p>Use Delphi from Codex, Claude Code, Cursor, or another MCP client.</p></div>
          </div>
        </section>

        <section className="closing-plate" id="install">
          <div className="closing-art">
            <ThemedImage variant="archive" />
          </div>
          <div className="closing-wash" aria-hidden="true" />
          <div className="closing-card reveal">
            <h2>Keep the source close.</h2>
            <p>Open source. Self-hosted. Ready in one command.</p>
            <div>
              <InstallChip />
              <Link className="text-action" href="https://github.com/synthetic-sciences/delphi#readme">
                Read the README <span aria-hidden="true">↗</span>
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="footer-grid">
          <div className="footer-intro">
            <div className="footer-brand"><BrandMark className="footer-mark" /><span>Delphi</span></div>
            <p>Local context for coding agents, by Synthetic Sciences.</p>
          </div>

          {FOOTER_COLUMNS.map((column) => (
            <div className="footer-column" key={column.title}>
              <h3>{column.title}</h3>
              <ul>
                {column.links.map(([label, href]) => (
                  <li key={label}><Link href={href}>{label}</Link></li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="footer-meta">
          <span>© {new Date().getFullYear()} InkVell Inc. Delphi is a Synthetic Sciences product.</span>
          <Link href="#top">Back to top ↑</Link>
        </div>
        <div className="footer-wordmark" aria-hidden="true">delphi</div>
      </footer>
    </>
  );
}
