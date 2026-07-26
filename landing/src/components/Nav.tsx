import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--line)] bg-[var(--nav-bg)] backdrop-blur-md">
      <div className="mx-auto flex h-14 w-full max-w-[1100px] items-center justify-between px-4 text-[14px] sm:px-6 md:px-8">
        <Link href="/" className="flex items-baseline gap-2.5">
          <span className="font-serif text-[20px] leading-none text-[var(--fg-strong)]">
            Delphi
          </span>
          <span className="hidden text-[12px] text-[var(--fg-mute)] sm:inline">
            Synthetic Sciences
          </span>
        </Link>
        <div className="flex items-center gap-4 text-[var(--fg-dim)] md:gap-7">
          <Link
            href="/#quickstart"
            className="hover:text-[var(--fg-strong)] transition-colors"
          >
            Docs
          </Link>
          <Link
            href="/#bench"
            className="hidden hover:text-[var(--fg-strong)] transition-colors sm:inline"
          >
            Benchmarks
          </Link>
          <Link
            href="https://github.com/synthetic-sciences/delphi"
            className="hover:text-[var(--fg-strong)] transition-colors"
          >
            GitHub
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
