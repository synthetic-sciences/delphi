import Image from "next/image";
import { FaqList } from "@/components/Faq";
import { InstallChip } from "@/components/InstallChip";
import { Reveal } from "@/components/Reveal";

/* Delphi. CMU Concrete throughout, Atlas-shaped layout. */

const H_HUGE = "text-[clamp(40px,5vw,72px)] leading-[1.02] tracking-[-0.024em]";
const H_BIG = "text-[clamp(30px,3.4vw,48px)] leading-[1.06] tracking-[-0.02em]";
const H_MED = "text-[22px] sm:text-[26px] leading-[1.14] tracking-[-0.012em]";
const P = "text-[14px] leading-[1.7] text-foreground/75";
const P_BIG = "text-[16px] sm:text-[17px] leading-[1.7] text-foreground/75";

const GITHUB = "https://github.com/synthetic-sciences/delphi";

/* Quiet product label above a heading. Same face as body text. */
function Eyebrow({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex items-center ${className}`}>
      <span className="text-[14px] tracking-[0.04em] text-foreground/70">{children}</span>
    </div>
  );
}

/* The one button system. Sharp corners; arrow nudges right on hover. */
function Cta({
  children,
  href = "#",
  variant = "primary",
  arrow = true,
  className = "",
}: {
  children: React.ReactNode;
  href?: string;
  variant?: "primary" | "ghost";
  arrow?: boolean;
  className?: string;
}) {
  const base =
    "group/cta inline-flex items-center justify-center gap-2.5 h-11 px-6 text-[14px] leading-none select-none";
  const look =
    variant === "primary"
      ? "btn-primary"
      : "border border-foreground/25 text-foreground/90 hover:border-foreground/55 hover:bg-foreground/[0.04] backdrop-blur-[2px] transition-colors duration-300";
  return (
    <a href={href} className={`${base} ${look} ${className}`}>
      {children}
      {arrow ? (
        <svg
          width="14"
          height="10"
          viewBox="0 0 14 10"
          aria-hidden
          className="transition-transform duration-300 group-hover/cta:translate-x-[3px]"
        >
          <path d="M0 5h12M8.5 1 13 5l-4.5 4" stroke="currentColor" strokeWidth="1.2" fill="none" />
        </svg>
      ) : null}
    </a>
  );
}

/* ------------------------- Product previews ---------------------------- */
/* Typographic mini-previews of real Delphi behavior, in the house style.  */

function SearchTerminal() {
  return (
    <div className="grain-overlay dot-grid h-full bg-background/60">
      <div className="flex items-center gap-1.5 border-b border-border/60 px-4 py-3">
        <span className="h-2 w-2 rounded-full bg-foreground/15" />
        <span className="h-2 w-2 rounded-full bg-foreground/15" />
        <span className="h-2 w-2 rounded-full bg-foreground/15" />
        <span className="ml-3 font-terminal text-[11px] text-foreground/40">delphi</span>
      </div>
      <div className="px-5 py-5 font-terminal text-[12px] sm:text-[13px] leading-[1.9]">
        <div className="text-foreground/85">
          <span className="text-foreground/40">$ </span>
          delphi search <span className="text-coral">&quot;where is session expiry enforced?&quot;</span>
        </div>
        <div className="mt-4 space-y-2">
          {[
            ["backend/synsc/auth/sessions.py", "cookie validation"],
            ["backend/synsc/api/http_server.py", "request path"],
            ["backend/tests/test_auth.py", "expected behavior"],
          ].map(([path, note]) => (
            <div key={path} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5">
              <span className="text-foreground/90">{path}</span>
              <span className="text-foreground/40">{note}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 text-olive">
          context pack ready, 3 files
          <span className="terminal-cursor" aria-hidden />
        </div>
      </div>
    </div>
  );
}

function CodeMini() {
  return (
    <div className="grain-overlay dot-grid h-full bg-background/60 p-5 font-terminal text-[11.5px] leading-[2]">
      <div className="text-foreground/90">
        validate_session <span className="text-foreground/35">synsc/auth/sessions.py</span>
      </div>
      <div className="mt-2 space-y-1">
        {[
          ["callers", "request_context, refresh_session"],
          ["callees", "decode_token, session_ttl"],
          ["tests", "test_auth.py, test_sessions.py"],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-4">
            <span className="w-14 shrink-0 text-coral/80">{k}</span>
            <span className="text-foreground/60">{v}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-border/60 pt-2.5 text-foreground/45">
        impact: 3 call sites across 2 modules
      </div>
    </div>
  );
}

function PaperMini() {
  return (
    <div className="grain-overlay dot-grid h-full bg-background/60 p-5 font-terminal text-[11.5px] leading-[2]">
      <div className="text-foreground/90">Attention Is All You Need</div>
      <div className="mt-2 space-y-1">
        {[
          ["section", "3.2 Scaled Dot-Product Attention"],
          ["equation", "softmax(QK^T / sqrt(d_k)) V"],
          ["citation", "Vaswani et al., 2017"],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-4">
            <span className="w-16 shrink-0 text-coral/80">{k}</span>
            <span className="text-foreground/60">{v}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-border/60 pt-2.5 text-foreground/45">
        quoted with source anchors, ready to cite
      </div>
    </div>
  );
}

function PackMini() {
  return (
    <div className="grain-overlay dot-grid h-full bg-background/60 p-5 font-terminal text-[11.5px] leading-[2]">
      <div className="flex gap-4">
        <span className="w-14 shrink-0 text-coral/80">task</span>
        <span className="text-foreground/85">fix cookie expiry bug</span>
      </div>
      <div className="flex gap-4">
        <span className="w-14 shrink-0 text-coral/80">budget</span>
        <span className="text-foreground/85">8,000 tokens</span>
      </div>
      <div className="mt-3 h-px w-full bg-border/80">
        <div className="h-px w-[72%] bg-olive/80" />
      </div>
      <div className="mt-3 space-y-1 text-foreground/60">
        <div>+ synsc/auth/sessions.py</div>
        <div>+ synsc/api/http_server.py</div>
        <div>+ tests/test_auth.py</div>
      </div>
    </div>
  );
}

function McpConfig() {
  return (
    <div className="grain-overlay bg-background/60 border border-border/60">
      <div className="flex items-center justify-between border-b border-border/60 px-5 py-3">
        <span className="font-terminal text-[11px] text-foreground/40">mcp.json</span>
        <span className="font-terminal text-[11px] text-foreground/40">any MCP client</span>
      </div>
      <pre className="overflow-x-auto px-5 py-5 font-terminal text-[12px] sm:text-[12.5px] leading-[1.8] text-foreground/80">
        {`{
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
}`}
      </pre>
    </div>
  );
}

/* ------------------------------- Page ---------------------------------- */

export default function Home() {
  return (
    <div id="top" className="min-h-screen bg-background text-foreground">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <main id="main-content">
        {/* ============================ HERO ============================ */}
        <section className="relative min-h-[100dvh] w-full overflow-hidden bg-background">
          <div className="absolute inset-x-0 top-0">
            <Image
              src="/img/heroes/sacred-way.png"
              alt="A robed scholar climbing the Sacred Way of Delphi, the Temple of Apollo on the slope of Mount Parnassus."
              width={1408}
              height={768}
              priority
              sizes="100vw"
              className="w-full h-auto min-h-[52dvh] object-cover object-[center_30%] select-none"
              style={{
                maskImage: "linear-gradient(to bottom, black 58%, transparent 99%)",
                WebkitMaskImage: "linear-gradient(to bottom, black 58%, transparent 99%)",
              }}
              draggable={false}
            />
          </div>

          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 z-[5]"
            style={{
              height: "68%",
              background:
                "linear-gradient(to top, hsl(30 14% 7%) 0%, hsl(30 14% 7% / 0.96) 20%, hsl(30 14% 7% / 0.72) 44%, hsl(30 14% 7% / 0.35) 70%, hsl(30 14% 7% / 0) 100%)",
            }}
          />

          <div className="absolute inset-0 z-10 mx-auto flex h-full max-w-[1400px] flex-col px-6 sm:px-10">
            <div className="hero-text rise self-start mt-[8vh]" style={{ animationDelay: "120ms" }}>
              <div className="font-display text-[clamp(52px,7.5vw,120px)] leading-[0.9] tracking-[-0.04em]">
                delphi
              </div>
              <a
                href="https://syntheticsciences.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-block text-[clamp(13px,1.2vw,17px)] tracking-[0.03em] text-foreground/70 transition-colors hover:text-foreground"
              >
                by Synthetic Sciences
              </a>
            </div>

            <div className="hero-text ml-auto mt-auto mb-[7vh] max-w-[820px] text-right">
              <div className="rise" style={{ animationDelay: "260ms" }}>
                <h1 className={`text-balance ${H_HUGE} text-foreground`}>
                  The right context,
                  <br />
                  before the code.
                </h1>
              </div>
              <div className="rise" style={{ animationDelay: "420ms" }}>
                <p className={`ml-auto mt-6 max-w-[52ch] ${P_BIG} text-foreground/80`}>
                  Delphi indexes your repos, docs, papers, and datasets, then
                  hands your coding agent precise, cited context over MCP.
                </p>
              </div>
              <div
                className="rise mt-9 flex flex-wrap items-center justify-end gap-3 [text-shadow:none]"
                style={{ animationDelay: "580ms" }}
              >
                <InstallChip />
                <Cta href={GITHUB} variant="ghost">
                  GitHub
                </Cta>
              </div>
            </div>
          </div>
        </section>

        {/* ========================= SOURCE STRIP ======================= */}
        <section aria-label="Supported source types" className="border-t border-border/40">
          <div className="mx-auto max-w-[1400px] px-6 py-11 text-center sm:px-10">
            <p className="text-[14px] text-foreground/45">Indexes</p>
            <ul className="mt-3 flex flex-wrap items-baseline justify-center gap-x-12 gap-y-3">
              {["Repositories", "Documentation", "Papers", "Datasets", "Local folders"].map(
                (s) => (
                  <li key={s} className="font-display text-[19px] sm:text-[21px] text-foreground/75">
                    {s}
                  </li>
                ),
              )}
            </ul>
          </div>
        </section>

        {/* ============== SEARCH / statement (dither-warm) ============== */}
        <section id="search" className="relative w-full overflow-hidden border-t border-border/40">
          <div className="relative z-10 mx-auto w-full max-w-[1400px] px-6 py-24 sm:px-10 sm:py-32">
            <div className="grid grid-cols-12 items-stretch gap-8 lg:gap-12">
              <Reveal className="col-span-12 lg:col-span-6">
                <div className="dither-warm flex h-full min-h-[420px] flex-col justify-center border border-border/40 p-8 sm:p-12">
                  <div className="dither-content">
                    <Eyebrow className="mb-6">Delphi Search</Eyebrow>
                    <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                      Your agent guesses. Delphi checks.
                    </h2>
                    <p className={`mt-7 max-w-[40ch] ${P_BIG} text-foreground/85`}>
                      Coding agents reach for stale training data. Delphi
                      searches the sources you actually build on and returns
                      the exact files, cited.
                    </p>
                  </div>
                </div>
              </Reveal>
              <Reveal delay={150} className="col-span-12 lg:col-span-6">
                <div className="h-full min-h-[420px] border border-border/40 overflow-hidden">
                  <SearchTerminal />
                </div>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ================== DETAIL GRID (hairline 3-up) ================ */}
        <section id="sources" className="relative w-full overflow-hidden border-t border-border/40">
          <div className="relative z-10 mx-auto w-full max-w-[1400px] px-6 py-24 sm:px-10 sm:py-32">
            <div className="max-w-[820px]">
              <Reveal>
                <h2 className={`text-balance ${H_BIG}`}>Ask once. Get the files.</h2>
              </Reveal>
              <Reveal delay={180}>
                <p className={`mt-6 max-w-[48ch] ${P_BIG}`}>
                  Every result links back to the line it came from.
                </p>
              </Reveal>
            </div>

            <div className="mt-16 grid grid-cols-12 gap-px border border-border/40 bg-border/40">
              {[
                {
                  visual: <CodeMini />,
                  title: "Code, with structure.",
                  body: "Symbols, callers, callees, and impact analysis, so the agent patches the right place instead of the first match.",
                },
                {
                  visual: <PaperMini />,
                  title: "Papers and docs, cited.",
                  body: "Sections, equations, and citations from the papers and versioned documentation behind your project.",
                },
                {
                  visual: <PackMini />,
                  title: "Context packs.",
                  body: "A task and a token budget in. A ranked pack of files out, sized to fit the next tool call.",
                },
              ].map((f, i) => (
                <Reveal key={f.title} delay={i * 90} className="col-span-12 bg-background md:col-span-4">
                  <div className="group flex h-full flex-col transition-colors duration-500 hover:bg-foreground/[0.02]">
                    <div className="border-b border-border/40 px-6 pb-4 pt-6 sm:px-8">
                      <div className="h-[240px] overflow-hidden border border-border/40 transition-all duration-500 group-hover:-translate-y-0.5 group-hover:border-foreground/35 motion-reduce:group-hover:translate-y-0">
                        {f.visual}
                      </div>
                    </div>
                    <div className="flex-1 p-7 sm:p-8">
                      <h3 className={H_MED}>{f.title}</h3>
                      <p className={`mt-3.5 max-w-[42ch] ${P}`}>{f.body}</p>
                    </div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ========= LOCAL / full-bleed statement (dither-purple) ======== */}
        <section id="local" className="dither-purple relative w-full overflow-hidden border-t border-border/40">
          <div className="dither-content mx-auto w-full max-w-[1400px] px-6 py-28 sm:px-10 sm:py-36">
            <div className="mx-auto max-w-[900px] text-center">
              <Reveal>
                <Eyebrow className="mb-6 justify-center">Local first</Eyebrow>
                <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                  Your code never leaves.
                </h2>
              </Reveal>
              <Reveal delay={200}>
                <p className={`mx-auto mt-7 max-w-[44ch] ${P_BIG} text-foreground/85`}>
                  The whole stack runs on your machine: PostgreSQL, pgvector,
                  and local embeddings. Index private work without sending it
                  anywhere.
                </p>
              </Reveal>
              <Reveal delay={320}>
                <div className="mt-8 flex flex-wrap justify-center gap-2 text-[13px]">
                  {["Apache 2.0", "No API key required"].map((t) => (
                    <span
                      key={t}
                      className="inline-flex items-center border border-foreground/30 bg-background/30 px-3 py-1.5 text-foreground/80 backdrop-blur-[2px]"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ==================== MCP (clean split) ======================= */}
        <section id="mcp" className="relative w-full overflow-hidden border-t border-border/40">
          <div className="relative z-10 mx-auto w-full max-w-[1400px] px-6 py-24 sm:px-10 sm:py-32">
            <div className="grid grid-cols-12 items-center gap-10 lg:gap-16">
              <Reveal className="col-span-12 lg:col-span-5">
                <h2 className={`text-balance ${H_BIG}`}>
                  Works with the agent you already use.
                </h2>
                <p className={`mt-6 max-w-[44ch] ${P_BIG}`}>
                  One small proxy connects Delphi to Claude Code, Cursor,
                  Windsurf, Claude Desktop, or anything else that speaks MCP.
                </p>
                <p className={`mt-4 max-w-[44ch] ${P}`}>
                  The installer writes this config for you. Search, symbol,
                  and context tools appear on the agent&apos;s next start.
                </p>
              </Reveal>
              <Reveal delay={150} className="col-span-12 lg:col-span-7">
                <McpConfig />
              </Reveal>
            </div>
          </div>
        </section>

        {/* ============================ FAQ ============================= */}
        <section id="faq" className="relative w-full overflow-hidden border-t border-border/40">
          <div className="relative z-10 mx-auto w-full max-w-[1400px] px-6 pb-14 pt-24 sm:px-10 sm:pb-16 sm:pt-32">
            <div className="grid grid-cols-12 gap-10 lg:gap-16">
              <div className="col-span-12 self-start lg:sticky lg:top-28 lg:col-span-5">
                <Reveal>
                  <h2 className={`text-balance ${H_BIG}`}>Frequently asked questions.</h2>
                  <p className={`mt-6 max-w-[36ch] ${P_BIG}`}>
                    Everything else lives in the README.
                  </p>
                </Reveal>
              </div>
              <div className="col-span-12 lg:col-span-7">
                <Reveal delay={120}>
                  <FaqList
                    items={[
                      {
                        q: "What is Delphi?",
                        a: "An open-source context engine for coding agents. It indexes your sources and serves search, symbols, and context packs to any MCP client.",
                      },
                      {
                        q: "What can it index?",
                        a: "Git repositories, documentation sites, research papers, Hugging Face datasets, and local folders that never had a remote.",
                      },
                      {
                        q: "Does my code leave my machine?",
                        a: "No. The API, workers, and database all run locally. Local sentence-transformer embeddings work without any external API key; OpenAI and Gemini embeddings are optional.",
                      },
                      {
                        q: "Which agents does it work with?",
                        a: "Claude Code, Cursor, Windsurf, Claude Desktop, and any other MCP client, through a small stdio proxy the installer configures for you.",
                      },
                      {
                        q: "What does it cost?",
                        a: "Nothing. Delphi is Apache 2.0 licensed and self-hosted. You bring the machine it runs on.",
                      },
                    ]}
                  />
                </Reveal>
              </div>
            </div>
          </div>
        </section>

        {/* ============ FINALE (full-bleed archive engraving) =========== */}
        <section id="install" className="relative min-h-[100dvh] w-full overflow-hidden border-t border-border/40">
          <div className="absolute inset-x-0 bottom-0">
            <Image
              src="/img/heroes/archive.png"
              alt="A vast Greek archive of scrolls and codices, a scribe reading by lamplight."
              width={1408}
              height={768}
              sizes="100vw"
              className="h-auto min-h-[52dvh] w-full select-none object-cover object-[center_70%]"
              style={{
                maskImage: "linear-gradient(to top, black 62%, transparent 99%)",
                WebkitMaskImage: "linear-gradient(to top, black 62%, transparent 99%)",
              }}
              draggable={false}
            />
          </div>

          <div
            className="pointer-events-none absolute inset-x-0 top-0 z-[5]"
            style={{
              height: "60%",
              background:
                "linear-gradient(to bottom, hsl(30 14% 7%) 0%, hsl(30 14% 7% / 0.96) 22%, hsl(30 14% 7% / 0.7) 48%, hsl(30 14% 7% / 0.32) 74%, hsl(30 14% 7% / 0) 100%)",
            }}
          />

          <div className="absolute inset-0 z-10 mx-auto flex h-full max-w-[1400px] flex-col px-6 sm:px-10">
            <div className="hero-text relative mt-[22vh] max-w-[820px] sm:mt-[34vh]">
              <span
                aria-hidden
                className="pointer-events-none absolute -inset-x-14 -inset-y-16 -z-10"
                style={{
                  background:
                    "radial-gradient(72% 92% at 34% 46%, hsl(30 14% 7% / 0.82) 0%, hsl(30 14% 7% / 0.48) 56%, transparent 80%)",
                }}
              />
              <Reveal>
                <h2 className={`text-balance ${H_HUGE} text-foreground`}>
                  Start with one command.
                </h2>
              </Reveal>
              <Reveal delay={180}>
                <p className={`mt-6 max-w-[44ch] ${P_BIG} text-foreground/90`}>
                  Open source and indexing in minutes. The dashboard and API
                  run on localhost.
                </p>
              </Reveal>
              <Reveal delay={300}>
                <div className="mt-9 flex flex-wrap items-center gap-3 [text-shadow:none]">
                  <InstallChip />
                  <Cta href={`${GITHUB}#readme`} variant="ghost" arrow={false}>
                    Read the README
                  </Cta>
                </div>
              </Reveal>
            </div>
          </div>
        </section>
      </main>

      {/* ============================ FOOTER ============================ */}
      <footer className="relative overflow-hidden">
        <div className="mx-auto max-w-[1400px] border-t border-border/40 px-6 pb-10 pt-16 text-[14px] text-muted sm:px-10">
          <div className="grid grid-cols-12 gap-10">
            <div className="col-span-12 md:col-span-6">
              <div className="font-display text-[22px] leading-none tracking-tight text-foreground">
                delphi
              </div>
              <p className="mt-4 max-w-[34ch] text-[13.5px] leading-[1.7] text-foreground/55">
                Local search for your agent&apos;s code, docs, and papers, by
                Synthetic Sciences.
              </p>
            </div>
            <div className="col-span-6 sm:col-span-4 md:col-span-3">
              <div className="mb-4 text-[13px] tracking-[0.04em] text-foreground/45">Resources</div>
              <ul className="space-y-2.5 text-[13.5px]">
                <li><a href="https://www.npmjs.com/package/@synsci/delphi" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">npm</a></li>
                <li><a href={GITHUB} className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">GitHub</a></li>
              </ul>
            </div>
            <div className="col-span-6 sm:col-span-4 md:col-span-3">
              <div className="mb-4 text-[13px] tracking-[0.04em] text-foreground/45">Company</div>
              <ul className="space-y-2.5 text-[13.5px]">
                <li>
                  <a
                    href="https://syntheticsciences.ai"
                    className="link-underline inline-flex items-center gap-1.5 text-foreground/70 hover:text-foreground"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Synthetic Sciences
                    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                      <path d="M2 8 L8 2 M4 2 L8 2 L8 6" stroke="currentColor" fill="none" />
                    </svg>
                  </a>
                </li>
                <li>
                  <a
                    href="https://tryatlas.sh"
                    className="link-underline inline-flex items-center gap-1.5 text-foreground/70 hover:text-foreground"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Atlas
                    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                      <path d="M2 8 L8 2 M4 2 L8 2 L8 6" stroke="currentColor" fill="none" />
                    </svg>
                  </a>
                </li>
                <li><a href="mailto:team@syntheticsciences.ai" className="link-underline text-foreground/70 hover:text-foreground">Contact</a></li>
                <li><a href="https://syntheticsciences.ai/privacy" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Privacy</a></li>
                <li><a href="https://syntheticsciences.ai/terms" className="link-underline text-foreground/70 hover:text-foreground" target="_blank" rel="noreferrer">Terms</a></li>
              </ul>
            </div>
          </div>

          <div className="mt-14 flex flex-col items-start justify-between gap-3 border-t border-border/40 pt-6 text-[12.5px] text-foreground/45 sm:flex-row sm:items-center">
            <div>&copy; {new Date().getFullYear()} InkVell Inc. Delphi is a Synthetic Sciences product.</div>
            <a href="#top" className="link-underline inline-flex items-center gap-2 hover:text-foreground">
              Back to top
              <svg width="9" height="11" viewBox="0 0 9 11" aria-hidden>
                <path d="M4.5 10V1.5M1 4.5 4.5 1 8 4.5" stroke="currentColor" fill="none" />
              </svg>
            </a>
          </div>
        </div>

        <div className="relative h-[15vw] max-h-[230px] min-h-[110px] overflow-hidden" aria-hidden>
          <div className="footer-watermark absolute left-1/2 top-[0.04em] -translate-x-1/2 text-center">
            delphi
          </div>
        </div>
      </footer>
    </div>
  );
}
