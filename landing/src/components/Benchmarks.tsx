import { Container } from "./Container";

const ROWS = [
  { metric: "Retrieval MRR",             delphi: "0.676", other: "0.505" },
  { metric: "Code QA accuracy",          delphi: "0.465", other: "0.208" },
  { metric: "Adversarial discrimination", delphi: "0.427", other: "0.185" },
  { metric: "Enhanced judge wins (of 164)", delphi: "110", other: "54" },
  { metric: "SWE-Agent parse rate",      delphi: "0.800", other: "0.720" },
];

export function Benchmarks() {
  return (
    <section
      id="bench"
      className="py-20 md:py-28 border-t border-[var(--line)]"
    >
      <Container>
        <h2 className="font-serif text-[34px] md:text-[44px] leading-[1.1] tracking-[-0.01em] text-[var(--fg-strong)] max-w-[680px]">
          Numbers.
        </h2>

        <div className="prose mt-10 text-[17.5px] leading-[1.7] text-[var(--fg-dim)] max-w-[680px] space-y-5">
          <p>
            We maintain a small open benchmark, the{" "}
            <a
              className="quiet"
              href="https://github.com/synthetic-sciences/SynsciContextBench"
            >
              SynsciContextBench
            </a>
            . Eleven phases (code retrieval, multi-hop, SWE-Agent
            code generation, diff-aware re-indexing, real-session
            replay, and more) against a fixed corpus of two popular
            Python libraries and their documentation. Same index,
            same embeddings, same queries. The numbers below are
            from the last full run.
          </p>
        </div>

        <div className="mt-12 max-w-[720px] border-t border-[var(--line)]">
          <div className="grid grid-cols-[1fr_auto_auto] gap-x-10 text-[13px] font-mono text-[var(--fg-mute)] py-3 border-b border-[var(--line)]">
            <span>Metric</span>
            <span className="text-right text-[var(--fg-strong)]">Delphi</span>
            <span className="text-right">Next best</span>
          </div>
          {ROWS.map((r) => (
            <div
              key={r.metric}
              className="grid grid-cols-[1fr_auto_auto] gap-x-10 py-3 border-b border-[var(--line)] text-[15px]"
            >
              <span className="text-[var(--fg)]">{r.metric}</span>
              <span className="text-right font-mono text-[var(--fg-strong)] tabular-nums">
                {r.delphi}
              </span>
              <span className="text-right font-mono text-[var(--fg-mute)] tabular-nums">
                {r.other}
              </span>
            </div>
          ))}
        </div>

        <p className="mt-8 text-[14px] text-[var(--fg-mute)] max-w-[680px] italic">
          Reproduce: <code className="font-mono not-italic">git clone github.com/synthetic-sciences/SynsciContextBench &amp;&amp; make bench</code>.
        </p>
      </Container>
    </section>
  );
}
