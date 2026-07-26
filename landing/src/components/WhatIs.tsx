import { Container } from "./Container";

export function WhatIs() {
  return (
    <section className="py-20 md:py-28 border-t border-[var(--line)]">
      <Container>
        <h2 className="font-serif text-[34px] md:text-[44px] leading-[1.1] tracking-[-0.01em] text-[var(--fg-strong)] max-w-[680px]">
          One index. Four sources.
        </h2>

        <div className="prose mt-10 text-[17.5px] leading-[1.7] text-[var(--fg-dim)] max-w-[680px] space-y-5">
          <p>
            Most retrieval engines specialise. They are good at code,
            or good at docs, or good at semantic search over PDFs.
            Delphi is built to hold all four{" "}
            <span className="italic">in the same index</span>. Code,
            documentation, papers, and datasets, so an agent can answer
            a single question by reaching across them.
          </p>
          <p>
            It speaks <span className="italic">Model Context Protocol</span>{" "}
            and plain HTTP. Plug it into Claude Code, Cursor, Windsurf,
            or any agent that grounds its answers in source material.
          </p>
        </div>
      </Container>
    </section>
  );
}
