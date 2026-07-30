/* What the product is and what it does, stated in terms of the operations it
 * actually exposes. This replaced a timeline of the project's own history,
 * which told a visitor nothing about whether the thing was worth installing. */

const SOURCES = [
  ["Repositories", "Cloned at a pinned commit, parsed for symbols, re-checked against the remote"],
  ["Documentation", "Crawled sites and hosted docs, chunked with their headings intact"],
  ["Papers", "arXiv and PDF ingest, with equations, citations, and code blocks pulled out"],
  ["Datasets", "HuggingFace dataset cards and their configs"],
] as const;

const CAPABILITIES = [
  {
    title: "Ask in the agent you already use",
    body: "89 tools over MCP, split into profiles so a coding agent is not handed the paper tooling by mistake. The same operations are on an HTTP API and a CLI.",
    calls: ["search_code", "search_symbols", "get_file"],
  },
  {
    title: "Get the file, not a link to it",
    body: "Results come back as ranked chunks with the retrieval branch that found each one attached, so a bad answer can be traced to the branch that produced it.",
    calls: ["build_context_pack", "get_context"],
  },
  {
    title: "Follow the code, not just the text",
    body: "Symbols are resolved into a call graph at index time. You can ask who calls a function and what breaks if you change it without another search.",
    calls: ["find_callers", "find_callees", "impact_analysis"],
  },
  {
    title: "Know when the index is stale",
    body: "Every source records the commit or fetch it came from. Freshness is a question you can ask rather than something you assume.",
    calls: ["check_freshness", "quick_index"],
  },
] as const;

export function ProductCapabilities() {
  return (
    <section
      id="product"
      className="border-b border-[var(--line)] py-24 md:py-36"
    >
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="grid gap-10 md:grid-cols-[0.8fr_1.2fr] md:gap-20">
          <div>
            <p className="eyebrow text-[var(--gold)]">What it does</p>
            <h2 className="section-title mt-5 max-w-[440px] text-[var(--fg-strong)]">
              Four kinds of source. One index. One question.
            </h2>
          </div>
          <div className="max-w-[640px] md:pt-8">
            <p className="text-[17px] leading-8 text-[var(--fg-dim)]">
              An agent working on real code needs the repository, the library
              docs, and sometimes the paper the algorithm came from. Delphi puts
              all four in one index so a single question can be answered from
              whichever of them holds the answer.
            </p>
          </div>
        </div>

        <div className="mt-16 grid gap-px border border-[var(--line)] bg-[var(--line)] sm:grid-cols-2 lg:grid-cols-4">
          {SOURCES.map(([title, body]) => (
            <div className="bg-[var(--bg)] p-6 md:p-7" key={title}>
              <h3 className="font-serif text-[21px] text-[var(--fg-strong)]">
                {title}
              </h3>
              <p className="mt-3 text-[13px] leading-6 text-[var(--fg-mute)]">
                {body}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-20 grid gap-x-16 gap-y-12 md:grid-cols-2">
          {CAPABILITIES.map((capability) => (
            <div
              className="border-t border-[var(--line-strong)] pt-6"
              key={capability.title}
            >
              <h3 className="font-serif text-[24px] leading-tight text-[var(--fg-strong)]">
                {capability.title}
              </h3>
              <p className="mt-4 max-w-[46ch] text-[15px] leading-7 text-[var(--fg-mute)]">
                {capability.body}
              </p>
              <p className="mt-5 flex flex-wrap gap-x-3 gap-y-2">
                {capability.calls.map((call) => (
                  <code
                    className="border border-[var(--line)] px-2 py-1 font-mono text-[11px] text-[var(--gold)]"
                    key={call}
                  >
                    {call}
                  </code>
                ))}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
