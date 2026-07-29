import { Container } from "./Container";

export function HowItWorks() {
  return (
    <section
      id="how"
      className="py-20 md:py-28 border-t border-[var(--line)]"
    >
      <Container>
        <h2 className="font-serif text-[34px] md:text-[44px] leading-[1.1] tracking-[-0.01em] text-[var(--fg-strong)] max-w-[680px]">
          Inside the engine.
        </h2>

        <div className="prose mt-10 text-[17.5px] leading-[1.7] text-[var(--fg-dim)] max-w-[680px] space-y-6">
          <p>
            Delphi is FastAPI in front of Postgres with{" "}
            <span className="font-mono text-[15px] text-[var(--fg)]">pgvector</span>{" "}
            for embeddings and tree-sitter for symbol extraction. The
            retrieval side is a hybrid: dense vectors, BM25 over text,
            trigram for fuzzy identifiers, and an exact-symbol channel.
            Results are fused per branch, then diversified at the file level
            without discarding the ranked candidate pool. Deployments can
            optionally add a cross-encoder re-rank.
          </p>
          <p>
            Documents are chunked by heading where headings exist, by
            symbol where they don&apos;t. The chunker preserves enclosing
            class and linked tests, so a hit comes back with the context
            an agent actually needs to act on it.
          </p>
          <p>
            For longer work, Delphi exposes an async research surface
            over server-sent events. Agents POST a question, get a session
            id, then stream iteration events as the engine searches,
            reads, and decides.
          </p>
        </div>
      </Container>
    </section>
  );
}
