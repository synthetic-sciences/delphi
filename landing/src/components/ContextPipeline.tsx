import { PIPELINE } from "@/lib/evidence";

export function ContextPipeline() {
  return (
    <section
      id="product"
      className="border-b border-[var(--line)] bg-[var(--bg-deep)] py-24 md:py-36"
    >
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="grid gap-12 lg:grid-cols-[0.82fr_1.18fr] lg:gap-24">
          <div>
            <p className="eyebrow text-[var(--gold)]">The system</p>
            <h2 className="section-title mt-5 max-w-[650px] text-[var(--fg-strong)]">
              Retrieval is one stage. The agent experiences all five.
            </h2>
            <p className="mt-8 max-w-[560px] text-[17px] leading-8 text-[var(--fg-dim)]">
              A context engine has to preserve source identity, recover the
              right evidence, fit it into a bounded window, and make every
              result inspectable. Optimizing only the search score misses the
              product.
            </p>
          </div>

          <ol className="border-t border-[var(--line-strong)]">
            {PIPELINE.map(([number, title, body]) => (
              <li
                className="grid grid-cols-[42px_105px_1fr] gap-3 border-b border-[var(--line)] py-6 sm:grid-cols-[52px_130px_1fr] sm:gap-5"
                key={number}
              >
                <span className="font-mono text-[10px] text-[var(--gold)]">
                  {number}
                </span>
                <strong className="font-serif text-[20px] font-normal text-[var(--fg-strong)]">
                  {title}
                </strong>
                <span className="text-[14px] leading-6 text-[var(--fg-mute)]">
                  {body}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="mt-24 grid gap-px border border-[var(--line)] bg-[var(--line)] sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Source control", "Immutable snapshots and freshness checks"],
            ["Five-way retrieval", "Vector, BM25, symbols, paths, trigrams"],
            ["Context assembly", "Bodies, siblings, tests, docs, imports"],
            ["Agent interface", "MCP, HTTP, CLI, and a local workspace"],
          ].map(([title, body]) => (
            <div className="bg-[var(--bg-deep)] p-6 md:p-8" key={title}>
              <h3 className="font-serif text-[23px] text-[var(--fg-strong)]">
                {title}
              </h3>
              <p className="mt-4 text-[13px] leading-6 text-[var(--fg-mute)]">
                {body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
