import Link from "next/link";

const REPO = "https://github.com/synthetic-sciences/delphi";

const COLUMNS = [
  {
    heading: "Project",
    links: [
      ["GitHub", REPO],
      ["npm", "https://www.npmjs.com/package/@synsci/delphi"],
      ["Releases", `${REPO}/releases`],
    ],
  },
  {
    heading: "Resources",
    links: [
      ["Docs", `${REPO}#quick-start`],
      ["Benchmarks", "/blog/context-engine-is-the-product"],
      ["Install", "/#install"],
      ["Apache 2.0", `${REPO}/blob/master/LICENSE`],
    ],
  },
  {
    heading: "Company",
    links: [
      ["Synthetic Sciences ↗", "https://syntheticsciences.ai"],
      ["Atlas ↗", "https://tryatlas.sh"],
      ["OpenScience ↗", "https://openscience.sh"],
    ],
  },
] as const;

export function SiteFooter() {
  return (
    <footer className="relative overflow-hidden border-t border-[var(--line)] bg-[var(--bg-deep)]">
      <div className="mx-auto w-full max-w-[1400px] px-6 pb-40 pt-16 sm:px-10 md:pb-48 md:pt-20">
        <div className="grid gap-12 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <div>
            <p className="font-serif text-[26px] tracking-[-0.03em] text-[var(--fg-strong)]">
              delphi
            </p>
            <p className="mt-3 max-w-[300px] text-[14px] leading-7 text-[var(--fg-mute)]">
              The open-source context engine for coding agents, by Synthetic
              Sciences.
            </p>
          </div>

          {COLUMNS.map((column) => (
            <div key={column.heading}>
              <p className="text-[14px] text-[var(--fg-dim)]">
                {column.heading}
              </p>
              <ul className="mt-5 space-y-3">
                {column.links.map(([label, href]) => (
                  <li key={label}>
                    <Link
                      className="text-[14px] text-[var(--fg-mute)] transition-colors hover:text-[var(--fg-strong)]"
                      href={href}
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-16 flex flex-wrap items-center justify-between gap-4 border-t border-[var(--line)] pt-6">
          <p className="text-[13px] text-[var(--fg-mute)]">
            © 2026 Synthetic Sciences. Apache 2.0.
          </p>
          <Link
            className="text-[13px] text-[var(--fg-mute)] transition-colors hover:text-[var(--fg-strong)]"
            href="#top"
          >
            Back to top ↑
          </Link>
        </div>
      </div>

      {/* Bleeds off the bottom edge; the footer's own overflow does the crop. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-[-0.3em] h-[190px]"
      >
        <span className="footer-watermark">delphi</span>
      </div>
    </footer>
  );
}
