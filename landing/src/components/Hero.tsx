import Link from "next/link";
import { Container } from "./Container";

export function Hero() {
  return (
    <section className="pt-16 pb-20 md:pt-24 md:pb-28 -mt-32 md:-mt-40 relative z-10">
      <Container>
        <h1 className="font-serif text-[56px] md:text-[80px] leading-[1.02] tracking-[-0.015em] text-[var(--fg-strong)]">
          Delphi.
        </h1>

        <p className="mt-8 text-[22px] md:text-[24px] leading-[1.45] text-[var(--fg)] max-w-[640px] font-serif">
          An open-source <span className="italic">MCP context engine.</span>
        </p>

        <p className="mt-6 text-[17px] leading-[1.65] text-[var(--fg-dim)] max-w-[620px]">
          Index code, docs, papers, and datasets. Serve your agents the
          right context, ranked. Built for the kind of research where
          retrieval is half the answer.
        </p>

        <div className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-4 text-[15px]">
          <Link
            href="#quickstart"
            className="text-[var(--fg-strong)] underline decoration-[var(--line-strong)] decoration-1 underline-offset-[6px] hover:decoration-[var(--fg)] transition-colors"
          >
            Get started
          </Link>
          <Link
            href="https://github.com/synthetic-sciences/delphi"
            className="text-[var(--fg-dim)] hover:text-[var(--fg-strong)] transition-colors"
          >
            github.com/synthetic-sciences/delphi →
          </Link>
        </div>
      </Container>
    </section>
  );
}
