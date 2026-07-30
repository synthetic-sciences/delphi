import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";

export function SiteNav({
  mode = "solid",
  showWordmark = true,
}: {
  mode?: "overlay" | "solid";
  /** The home hero sets the wordmark at full size beneath the bar, so the bar
   *  itself carries only the links there. Everywhere else it needs the mark. */
  showWordmark?: boolean;
}) {
  const overlay = mode === "overlay";

  return (
    <header
      className={
        overlay
          ? "absolute inset-x-0 top-0 z-40 text-[#f7f0dc]"
          : "sticky top-0 z-40 border-b border-[var(--line)] bg-[var(--nav-bg)] backdrop-blur-xl"
      }
    >
      <div
        className={`mx-auto flex h-[68px] w-full items-center justify-between ${
          overlay
            ? "max-w-[1400px] px-6 sm:px-10"
            : "max-w-[1240px] px-5 sm:px-8"
        }`}
      >
        {showWordmark ? (
          <Link
            href="/"
            aria-label="Delphi home"
            className="focus-ring flex items-baseline gap-3"
          >
            <span
              className={`font-serif text-[25px] leading-none tracking-[-0.03em] ${
                overlay ? "text-[#fff8e8]" : "text-[var(--fg-strong)]"
              }`}
            >
              delphi
            </span>
            <span
              className={`hidden font-mono text-[9px] uppercase tracking-[0.2em] sm:inline ${
                overlay ? "text-[#d8cdb3]" : "text-[var(--fg-mute)]"
              }`}
            >
              Synthetic Sciences
            </span>
          </Link>
        ) : (
          <span />
        )}

        <nav
          aria-label="Primary navigation"
          className={`flex items-center gap-4 font-mono text-[10px] uppercase tracking-[0.14em] sm:gap-6 ${
            overlay ? "text-[#e8deca]" : "text-[var(--fg-dim)]"
          }`}
        >
          <Link
            href="/#product"
            className="focus-ring hidden transition-colors hover:text-[var(--gold)] md:inline"
          >
            Product
          </Link>
          <Link
            href="/#results"
            className="focus-ring hidden transition-colors hover:text-[var(--gold)] md:inline"
          >
            Results
          </Link>
          <Link
            href="/blog"
            className="focus-ring transition-colors hover:text-[var(--gold)]"
          >
            Blog
          </Link>
          <Link
            href="https://github.com/synthetic-sciences/delphi#quick-start"
            className="focus-ring hidden transition-colors hover:text-[var(--gold)] sm:inline"
          >
            Docs
          </Link>
          <Link
            href="https://github.com/synthetic-sciences/delphi"
            className="focus-ring transition-colors hover:text-[var(--gold)]"
          >
            GitHub
          </Link>
          <ThemeToggle tone={overlay ? "inverse" : "default"} />
        </nav>
      </div>
    </header>
  );
}
