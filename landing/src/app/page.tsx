import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import { ThemedImage } from "@/components/HeroImage";
import { InstallChip } from "@/components/InstallChip";
import { ThemeToggle } from "@/components/ThemeToggle";

const files = [
  ["backend/synsc/auth/sessions.py", "session lifetime and cookie policy"],
  ["backend/synsc/api/http_server.py", "login route and response headers"],
  ["backend/tests/test_auth.py", "the behavior the change must keep"],
];

const sources = [
  ["code", "synthetic-sciences/delphi"],
  ["docs", "local documentation"],
  ["papers", "saved research"],
];

export default function Home() {
  return (
    <main>
      <section className="hero">
        <div className="hero-art" aria-hidden="true">
          <ThemedImage variant="sacred-way" priority />
        </div>
        <div className="hero-wash" />

        <header className="site-header">
          <Link aria-label="Delphi home" className="brand" href="/">
            <BrandMark className="brand-mark" />
            <span>Delphi</span>
          </Link>
          <ThemeToggle />
        </header>

        <div className="hero-copy">
          <p className="eyebrow">Local context for agents</p>
          <h1>Give your agent the right files.</h1>
          <p className="hero-dek">Code, docs, and papers. Indexed locally.</p>
          <div className="hero-actions">
            <InstallChip />
            <Link
              className="text-link"
              href="https://github.com/synthetic-sciences/delphi"
            >
              View on GitHub <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </div>
      </section>

      <section className="story-section">
        <div className="story-copy">
          <p className="eyebrow">01 / Index</p>
          <h2>Build one local index.</h2>
          <p>
            Add code, docs, and papers. Delphi keeps them searchable on your
            machine.
          </p>
        </div>

        <figure className="source-map" aria-label="A local Delphi index">
          <div className="visual-bar">
            <span>local / delphi</span>
            <span className="status-dot">ready</span>
          </div>
          <div className="source-list">
            {sources.map(([name, detail], index) => (
              <div className="source-row" key={name}>
                <span className="source-number">0{index + 1}</span>
                <strong>{name}</strong>
                <span>{detail}</span>
                <i aria-hidden="true" />
              </div>
            ))}
          </div>
          <div className="index-core">
            <BrandMark className="index-mark" />
            <span>local index</span>
          </div>
          <div className="map-lines" aria-hidden="true" />
        </figure>
      </section>

      <section className="story-section story-section-reverse">
        <div className="story-copy">
          <p className="eyebrow">02 / Ask</p>
          <h2>See the files behind the answer.</h2>
          <p>
            Delphi returns the code, nearby context, and related tests.
          </p>
        </div>

        <figure className="answer-visual">
          <div className="visual-bar">
            <span>agent request</span>
            <span>local</span>
          </div>
          <blockquote>
            Where is session expiry enforced, and which test covers it?
          </blockquote>
          <div className="answer-rule" />
          <figcaption>context pack / 3 files</figcaption>
          <div className="file-stack">
            {files.map(([path, note], index) => (
              <div className="file-row" key={path}>
                <span>{index + 1}</span>
                <div>
                  <strong>{path}</strong>
                  <small>{note}</small>
                </div>
                <span aria-hidden="true">↗</span>
              </div>
            ))}
          </div>
        </figure>
      </section>

      <section className="image-story">
        <div className="image-story-art" aria-hidden="true">
          <ThemedImage variant="archive" />
        </div>
        <div className="image-story-wash" />
        <div className="image-story-copy">
          <p className="eyebrow">03 / Keep it local</p>
          <h2>It runs on your machine.</h2>
          <p>Use a laptop or your own infrastructure.</p>
        </div>
      </section>

      <section className="install-section" id="install">
        <BrandMark className="install-mark" />
        <div>
          <p className="eyebrow">Open source · Apache 2.0</p>
          <h2>Start with one command.</h2>
        </div>
        <InstallChip />
      </section>

      <footer className="site-footer">
        <span>Delphi</span>
        <Link href="https://syntheticsciences.ai">Synthetic Sciences ↗</Link>
      </footer>
    </main>
  );
}
