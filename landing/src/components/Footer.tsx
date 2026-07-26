import Link from "next/link";
import { Container } from "./Container";

export function Footer() {
  return (
    <footer className="mt-8 py-14 border-t border-[var(--line)]">
      <Container>
        <div className="flex flex-wrap items-baseline justify-between gap-6 text-[14px] text-[var(--fg-mute)]">
          <div className="flex items-baseline gap-2">
            <span className="font-serif text-[18px] text-[var(--fg)]">
              Delphi
            </span>
            <span>·</span>
            <Link
              href="https://syntheticsciences.ai"
              className="hover:text-[var(--fg)] transition-colors"
            >
              Synthetic Sciences
            </Link>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link
              href="https://github.com/synthetic-sciences/delphi"
              className="hover:text-[var(--fg)] transition-colors"
            >
              GitHub
            </Link>
            <Link
              href="https://github.com/synthetic-sciences/SynsciContextBench"
              className="hover:text-[var(--fg)] transition-colors"
            >
              Benchmark
            </Link>
            <Link
              href="https://github.com/synthetic-sciences/delphi/blob/master/LICENSE"
              className="hover:text-[var(--fg)] transition-colors"
            >
              Apache 2.0
            </Link>
            <Link
              href="mailto:hello@syntheticsciences.ai"
              className="hover:text-[var(--fg)] transition-colors"
            >
              hello@syntheticsciences.ai
            </Link>
          </div>
        </div>

        <p className="mt-8 text-[12px] text-[var(--fg-mute)] italic">
          © 2026 Synthetic Sciences.
        </p>
      </Container>
    </footer>
  );
}
