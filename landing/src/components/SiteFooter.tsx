import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-[var(--line)] bg-[var(--bg-deep)]">
      <div className="mx-auto grid w-full max-w-[1240px] gap-12 px-5 py-14 sm:px-8 md:grid-cols-[1.4fr_1fr] md:py-20">
        <div>
          <p className="font-serif text-[30px] tracking-[-0.03em] text-[var(--fg-strong)]">
            delphi
          </p>
          <p className="mt-3 max-w-[420px] text-[15px] leading-7 text-[var(--fg-mute)]">
            Open-source context infrastructure for agents that need to reason
            over real software and research.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-8 font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--fg-mute)]">
          <div className="space-y-4">
            <Link className="footer-link" href="/blog">
              Research blog
            </Link>
            <Link
              className="footer-link"
              href="https://github.com/synthetic-sciences/delphi"
            >
              GitHub
            </Link>
            <Link
              className="footer-link"
              href="https://github.com/synthetic-sciences/delphi#quick-start"
            >
              Documentation
            </Link>
          </div>
          <div className="space-y-4">
            <Link
              className="footer-link"
              href="https://github.com/synthetic-sciences/delphi/blob/master/LICENSE"
            >
              Apache 2.0
            </Link>
            <Link
              className="footer-link"
              href="mailto:hello@syntheticsciences.ai"
            >
              Contact
            </Link>
            <Link
              className="footer-link"
              href="https://syntheticsciences.ai"
            >
              Synthetic Sciences
            </Link>
          </div>
        </div>
        <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-[var(--fg-mute)] md:col-span-2">
          © 2026 Synthetic Sciences · Built in the open
        </p>
      </div>
    </footer>
  );
}

